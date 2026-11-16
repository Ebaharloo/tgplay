"""tp.playlist - the episode loop: provider + proxy + cache + player + skip.

No module-level state: one Playlist instance owns the run, and everything it
needs is injected. Handles resume, retry-on-open-failure, skip, cut/start and
the --next prefetch trigger (via the player's PosWatcher).
"""
import json
import os
import re
import threading
import time
import urllib.parse
from typing import List, Optional

from . import log
from .episodes import Episode
from .player import PosWatcher

# Mark an episode watched once this fraction played (even if the user quits).
WATCHED_FRAC = float(os.environ.get('AGP_WATCHED_FRAC', '0.70'))


def _safe(fn, *a, **k):
    try:
        fn(*a, **k)
        return True
    except Exception as ex:
        log.cprint(f'track: sync failed ({ex})')
        return False


class Playlist:
    def __init__(self, provider, proxy, cache, player, config, *,
                 skip=None, prefetcher=None, tracker=None, interval: float = 3.0,
                 mal_id=None, stop=None):
        self.provider = provider
        self.proxy = proxy
        self.cache = cache
        self.player = player
        self.cfg = config
        self.skip = skip
        self.prefetcher = prefetcher
        self.tracker = tracker
        self.mal_id = mal_id          # pinned show id: ani-skip needs it
        self.stop_ev = stop           # set by Session.stop -> end the playlist
        self.interval = float(os.environ.get('AGP_WATCH_INTERVAL', interval))

    # --- progress ----------------------------------------------------------
    def _load(self):
        try:
            return json.load(open(self.cfg.progress))
        except Exception:
            return {}

    def progress_for(self, title: str):
        return self._load().get(title)

    def _save(self, title: str, ep: int, pos: float):
        d = self._load()
        d[title] = {'ep': ep, 'pos': round(pos)}
        from .config import save_json           # atomic: crash-safe resume
        save_json(self.cfg.progress, d)

    # --- helpers -----------------------------------------------------------
    def _name(self, ep: Episode, stream) -> str:
        url = getattr(stream, 'url', None)
        if url:
            m = re.search(r'/([^/?]+\.mkv)', url)
            if m:
                return urllib.parse.unquote(m.group(1))
        try:
            dn = self.provider.display_name(ep.num)
        except Exception:
            dn = None
        return dn or f'{self.provider.title} - ({ep.num}).mkv'

    def _trigger(self, cut, frac):
        if frac == 'cut':
            def fire(p, d):
                return bool(d) and p >= d - 60
        else:
            def fire(p, d):
                eff = (d - cut) if (isinstance(cut, int) and d) else d
                return bool(eff) and p / eff > frac
        return fire

    # --- loop --------------------------------------------------------------
    def run(self, episodes: List[Episode], *, skip_mode: str = 'all',
            skip_toggle: bool = False, cut: Optional[int] = None,
            start: Optional[int] = None, next_frac=False,
            extra: Optional[List[str]] = None):
        title = self.provider.title
        for i, ep in enumerate(episodes):
            if self.stop_ev is not None and self.stop_ev.is_set():
                return 'stopped'
            nxt = episodes[i + 1] if i + 1 < len(episodes) else None
            attempt = 0
            while True:
                t_ep = time.monotonic()
                stream = self.provider.stream(ep.num)
                name = self._name(ep, stream)
                t_link = time.monotonic() - t_ep
                direct = getattr(stream, 'direct', False)
                extra_direct: List[str] = []
                head_warm = False
                probe_url, probe_hdr = None, None
                if direct:
                    # HLS/DASH: mpv plays the remote URL itself (no proxy)
                    url = stream.url
                    ref = (getattr(stream, 'headers', {}) or {}).get('Referer')
                    if ref:
                        extra_direct.append(f'--referrer={ref}')
                    # HLS carries chapters in the manifest, so probe the same
                    # URL mpv will play (that was the dead-skip bug: direct
                    # streams were never probed)
                    probe_url, probe_hdr = stream.url, (stream.headers or {})
                    for _lbl, sub in (getattr(stream, 'subs', []) or []):
                        extra_direct.append(f'--sub-file={sub}')
                else:
                    self.proxy.register(name, stream)
                    ready = threading.Event()
                    self.proxy.prewarm(name, ready)
                    # brief head peek only - then start: the prewarm keeps
                    # filling the head in the background and the proxy
                    # live-reads any gap mpv asks for in the meantime
                    head_warm = ready.wait(2)
                    url = self.proxy.url(name)
                    t_link = time.monotonic() - t_ep   # incl. head warm-up
                    if head_warm:
                        probe_url = url
                log.cprint(f'load: ep{ep.num} link + head peek in '
                           f'{t_link:.1f}s ({"hls" if direct else "proxy"})')

                flags, note = [], 'off'
                t_sk = time.monotonic()
                if self.skip is not None:
                    try:
                        flags, note = self.skip.flags(
                            title=title, ep=ep.num,
                            url=probe_url, headers=probe_hdr,
                            mode=skip_mode,
                            toggle=skip_toggle, timeout=6,
                            mal_id=self.mal_id or getattr(
                                self.provider, 'mal_id', None))
                    except Exception as ex:
                        flags, note = [], f'failed ({ex})'
                log.cprint(f'skip[{skip_mode}]: {note} '
                           f'in {time.monotonic() - t_sk:.1f}s')

                sock = f'/tmp/tgplay-{os.getpid()}-{ep.num}.ipc'
                fire = None
                on_fire = None
                if next_frac and nxt is not None and self.prefetcher is not None \
                        and not direct:
                    fire = self._trigger(cut, next_frac)

                    def on_fire(_nxt=nxt):
                        try:
                            st = self.provider.stream(_nxt.num)
                            nm = self._name(_nxt, st)
                            log.cprint(f'next: prefetching ep{_nxt.num}')
                            def _pf(_nm=nm, _st=st):
                                p = self.prefetcher.prefetch(_nm, _st)
                                if p and self.proxy is not None:
                                    lo = self.prefetcher.publish(self.proxy,
                                                                 _nm, p)
                                    log.cprint(f'next: ep{_nxt.num} prefetched '
                                               f'from {lo} ' 'bytes - proxy '
                                               'will serve it from disk')
                            threading.Thread(target=_pf, daemon=True).start()
                        except Exception:
                            pass

                fired = [False]

                def _tick(p, _n=ep.num):
                    if not fired[0]:
                        fired[0] = True
                        log.cprint(f'mpv: ep{_n} window up in '
                                   f'{time.monotonic() - t_ep:.1f}s')
                    self._save(title, _n, p)

                watcher = PosWatcher(
                    sock, self.interval,
                    on_pos=_tick,
                    fire_when=fire, on_fire=on_fire)
                ep_start = start if i == 0 else None
                if i == 0 and start is not None:
                    log.cprint(f'start: ep{ep.num} at {int(start)}s')
                elif i == 0:
                    log.cprint(f'start: ep{ep.num} at 0s (no saved position)')
                watcher.start()
                self._scrobble('start', ep.num, 0)
                cmd = self.player.command(
                    url, title=name, extra=(list(extra or []) + extra_direct + flags),
                    start=ep_start, cut=cut, ipc=sock)
                tag = (f'  [start {int(ep_start)}s]' if ep_start is not None else '')
                if cut:
                    tag += f'  [cut {cut}s]'
                if flags:
                    tag += '  [skip]'
                log.cprint(f'>> streaming ep{ep.num}: {name}{tag}')
                if self.stop_ev is not None and self.stop_ev.is_set():
                    watcher.join(timeout=1)
                    return 'stopped'
                rc = self.player.play(cmd)
                if self.stop_ev is not None and self.stop_ev.is_set():
                    # Stop = end the playlist; mpv's exit code is not a retry
                    log.cprint('stopped: playlist ended by the user')
                    return 'stopped'
                if rc == 1:                       # mpv missing / bad flags
                    log.cprint('player: mpv could not start (missing binary '
                               'or bad flags) - stopping here')
                    watcher.join(timeout=1)
                    return
                watcher.join(timeout=12)
                try:
                    os.remove(sock)
                except OSError:
                    pass

                dur = getattr(watcher, 'duration', 0) or 0
                pos = getattr(watcher, 'last', 0) or 0
                frac = (pos / dur) if dur else 0.0
                self._scrobble('stop', ep.num, frac * 100)
                finished = (rc == 0) or (frac >= WATCHED_FRAC)

                if rc == 4:  # user quit
                    if finished:
                        log.cprint(f'watched: {frac:.0%} of ep{ep.num} — '
                                   'syncing to trackers')
                        self._save(title, ep.num + 1, 0)
                        self._mark(ep.num)
                    return
                if rc == 2 and attempt < 2:  # failed to open: fresh link, retry
                    attempt += 1
                    try:
                        self.proxy.streams.pop(name, None)
                    except Exception:
                        pass
                    rot = getattr(self.provider, 'rotate', None)
                    if callable(rot):
                        try:
                            rot()          # try the next server (animex)
                        except Exception:
                            pass
                    log.cprint(f'load: ep{ep.num} failed to open -> retry {attempt}')
                    continue
                if finished:
                    if rc != 0:
                        log.cprint(f'watched: {frac:.0%} of ep{ep.num} — '
                                   'syncing to trackers')
                    self._save(title, ep.num + 1, 0)
                    self._mark(ep.num)
                break
        log.cprint('>> done')

    def _scrobble(self, action, num, progress):
        """Report playback progress (start / stop) from a worker thread: a slow
        API must never hold up mpv."""
        tracker = self.tracker
        fn = getattr(tracker, 'scrobble', None)
        if fn is None:
            return
        try:
            if not tracker.enabled():
                return
        except Exception:
            return
        mal = self.mal_id or getattr(self.provider, 'mal_id', None)
        anilist = getattr(self.provider, 'anilist_id', None)
        threading.Thread(
            target=_safe, daemon=True,
            args=(fn, self.provider.title, num, progress),
            kwargs={'action': action, 'mal': mal, 'anilist': anilist}).start()

    def _mark(self, num):
        if self.tracker is None:
            return
        try:
            if not self.tracker.enabled():
                return
        except Exception:
            return
        mal = self.mal_id or getattr(self.provider, 'mal_id', None)
        anilist = getattr(self.provider, 'anilist_id', None)
        if not mal and not anilist:
            meta = getattr(self.skip, 'meta', None) if self.skip else None
            if meta is not None:
                try:
                    mal = meta.resolve_mal(self.provider.title, ask=False)
                except Exception:
                    mal = None
        def work():
            t0 = time.monotonic()
            if _safe(self.tracker.mark_watched, self.provider.title,
                     num, mal=mal, anilist=anilist):
                log.cprint(f'track: ep{num} synced in '
                           f'{time.monotonic() - t0:.1f}s')
        threading.Thread(target=work, daemon=True).start()
