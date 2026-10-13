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
                 skip=None, prefetcher=None, tracker=None, interval: float = 3.0):
        self.provider = provider
        self.proxy = proxy
        self.cache = cache
        self.player = player
        self.cfg = config
        self.skip = skip
        self.prefetcher = prefetcher
        self.tracker = tracker
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
        os.makedirs(os.path.dirname(self.cfg.progress), exist_ok=True)
        json.dump(d, open(self.cfg.progress, 'w'))

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
            nxt = episodes[i + 1] if i + 1 < len(episodes) else None
            attempt = 0
            while True:
                t_ep = time.monotonic()
                stream = self.provider.stream(ep.num)
                name = self._name(ep, stream)
                t_link = time.monotonic() - t_ep
                direct = getattr(stream, 'direct', False)
                extra_direct: List[str] = []
                if direct:
                    # HLS/DASH: mpv plays the remote URL itself (no proxy)
                    url = stream.url
                    ref = (getattr(stream, 'headers', {}) or {}).get('Referer')
                    if ref:
                        extra_direct.append(f'--referrer={ref}')
                    for _lbl, sub in (getattr(stream, 'subs', []) or []):
                        extra_direct.append(f'--sub-file={sub}')
                else:
                    self.proxy.register(name, stream)
                    ready = threading.Event()
                    self.proxy.prewarm(name, ready)
                    ready.wait(25)
                    url = self.proxy.url(name)
                    t_link = time.monotonic() - t_ep   # incl. head warm-up
                log.cprint(f'load: ep{ep.num} link + head ready in '
                           f'{t_link:.1f}s ({"hls" if direct else "proxy"})')

                flags, note = [], 'off'
                t_sk = time.monotonic()
                if self.skip is not None:
                    try:
                        flags, note = self.skip.flags(
                            title=title, ep=ep.num,
                            url=None if direct else url, mode=skip_mode,
                            toggle=skip_toggle,
                            mal_id=getattr(self.provider, 'mal_id', None))
                    except Exception as ex:
                        flags, note = [], f'failed ({ex})'
                if i == 0:
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
                            threading.Thread(
                                target=self.prefetcher.prefetch,
                                args=(nm, st), daemon=True).start()
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
                cmd = self.player.command(
                    url, title=name, extra=(list(extra or []) + extra_direct + flags),
                    start=ep_start, cut=cut, ipc=sock)
                tag = (f'  [start {int(ep_start)}s]' if ep_start is not None else '')
                if cut:
                    tag += f'  [cut {cut}s]'
                if flags:
                    tag += '  [skip]'
                log.cprint(f'>> streaming ep{ep.num}: {name}{tag}')
                rc = self.player.play(cmd)
                watcher.join(timeout=12)
                try:
                    os.remove(sock)
                except OSError:
                    pass

                dur = getattr(watcher, 'duration', 0) or 0
                pos = getattr(watcher, 'last', 0) or 0
                frac = (pos / dur) if dur else 0.0
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

    def _mark(self, num):
        if self.tracker is None:
            return
        try:
            if not self.tracker.enabled():
                return
        except Exception:
            return
        mal = getattr(self.provider, 'mal_id', None)
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
