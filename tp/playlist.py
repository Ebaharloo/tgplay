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
from .player import PosWatcher, ipc_seek
from .prefetch import hls_to_file
from .skip import probe_targets

# Mark an episode watched once this fraction played (even if the user quits).
WATCHED_FRAC = float(os.environ.get('AGP_WATCHED_FRAC', '0.70'))
# Seconds of playback between /scrobble/pause pushes (Simkl locks writes 20 s).
PAUSE_EVERY = float(os.environ.get('AGP_PAUSE_EVERY', '60'))


def _safe(fn, *a, **k):
    try:
        fn(*a, **k)
        return True
    except Exception as ex:
        log.cprint(f'track: sync failed ({ex})')
        return False


def _behind(pos, start) -> bool:
    """True when mpv opened at the top although a Start-at was requested.
    mpv silently drops --start on some streams; the watcher seeks instead."""
    return (isinstance(start, int) and start > 15
            and isinstance(pos, (int, float)) and pos < start - 15)


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
        self._pause_at = 0.0          # position of the last Simkl pause push
        self._pre: dict = {}          # ep num -> warmed by the running episode

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

    def _warm(self, ep):
        """Warm the next episode while this one still plays: its link, its skip
        flags, and - for HLS, which has no size to mirror - the bytes, pulled
        to disk by ffmpeg. The next start then costs no network at all."""
        try:
            st = self.provider.stream(ep.num)
        except Exception as ex:
            log.cprint(f'next: ep{ep.num} link failed ({ex})')
            return
        name = self._name(ep, st)
        warm = {'name': name, 'flags': None, 'path': None,
                'ev': threading.Event(),
                'subs': [f'--sub-file={u}' for _l, u in
                         (getattr(st, 'subs', []) or [])]}
        self._pre[ep.num] = warm
        log.cprint(f'next: warming ep{ep.num} ({name})')
        if self.skip is not None:
            # proxied streams: the same bytes through our proxy answer when the
            # origin hides chapters; direct HLS has no proxy to fall back to
            if self.proxy is not None and not getattr(st, 'direct', False):
                # register here, not just in the main loop: the probe URL must
                # be servable, and publish() needs the name to set_local
                self.proxy.register(name, st)
                proxy_url = self.proxy.url(name)
            else:
                proxy_url = None
            try:
                warm['flags'], note = self.skip.flags(
                    title=self.provider.title, ep=ep.num,
                    targets=probe_targets(st, proxy_url),
                    mode=self._skip_mode, toggle=self._skip_toggle,
                    timeout=6, mal_id=self.mal_id or getattr(
                        self.provider, 'mal_id', None))
                log.cprint(f'next: ep{ep.num} skip ready ({note})')
            except Exception:
                pass
        if getattr(st, 'direct', False) and self.cache is not None:
            safe = re.sub(r'[^A-Za-z0-9._-]', '_', name)
            self._sweep_hls()          # warmed files are one-shot: keep 2 days
            out = os.path.join(self.cache.path('hls'), safe)
            if not out.lower().endswith(('.mkv', '.mp4')):
                out = os.path.splitext(out)[0] + '.mkv'
            os.makedirs(os.path.dirname(out), exist_ok=True)
            t0 = time.monotonic()
            if hls_to_file(st.url, getattr(st, 'headers', None), out):
                warm['path'] = out
                log.cprint(f'next: ep{ep.num} on disk '
                           f'({os.path.getsize(out) // 1048576}MB in '
                           f'{time.monotonic() - t0:.0f}s)')
            else:
                log.cprint(f'next: ep{ep.num} stayed remote '
                           '(download did not finish in time)')
            warm['ev'].set()
            return
        if not warm['flags']:
            warm['flags'] = []          # probe done: do not repeat it
        p = self.prefetcher.prefetch(name, st)
        if p and self.proxy is not None:
            lo = self.prefetcher.publish(self.proxy, name, p)
            log.cprint(f'next: ep{ep.num} prefetched from {lo} bytes - '
                       'proxy will serve it from disk')
        warm['ev'].set()

    def _sweep_hls(self, days: float = 2.0):
        d = self.cache.path('hls')
        cut = time.time() - days * 86400
        try:
            for f in os.listdir(d):
                p = os.path.join(d, f)
                if os.path.isfile(p) and os.path.getmtime(p) < cut:
                    os.remove(p)
        except OSError:
            pass

    def _trigger(self, cut, frac, end=None):
        # the stream stops at `end` when set, so the trigger must measure
        # against that shorter length or it never fires
        def stop(d):
            return min(d, end) if (end and d) else d

        if frac == 'cut':
            def fire(p, d):
                return bool(d) and p >= (stop(d) or d) - 60
        else:
            def fire(p, d):
                d = stop(d)
                eff = (d - cut) if (isinstance(cut, int) and d) else d
                return bool(eff) and p / eff > frac
        return fire

    # --- loop --------------------------------------------------------------
    def run(self, episodes: List[Episode], *, skip_mode: str = 'all',
            skip_toggle: bool = False, cut: Optional[int] = None,
            start: Optional[int] = None, end: Optional[int] = None,
            next_frac=False, extra: Optional[List[str]] = None):
        title = self.provider.title
        self._skip_mode, self._skip_toggle = skip_mode, skip_toggle
        for i, ep in enumerate(episodes):
            if self.stop_ev is not None and self.stop_ev.is_set():
                return 'stopped'
            nxt = episodes[i + 1] if i + 1 < len(episodes) else None
            attempt = 0
            while True:
                t_ep = time.monotonic()
                warm = self._pre.pop(ep.num, None) or {}
                ev = warm.get('ev')
                if ev is not None and not warm.get('path') and not ev.is_set():
                    t_w = time.monotonic()
                    if ev.wait(float(os.environ.get('AGP_PREFETCH_WAIT', '25'))):
                        log.cprint(f'next: ep{ep.num} download finished while '
                                   f'we waited {time.monotonic() - t_w:.0f}s')
                flags, note = [], 'off'
                if 'flags' in warm:
                    flags, note = warm['flags'] or [], 'prefetched'
                if warm.get('path') and os.path.exists(warm['path']):
                    # HLS pulled to disk while the previous episode played:
                    # no scrape, no skip probe, mpv opens a local file
                    name, url = warm['name'], warm['path']
                    direct, head_warm = False, True
                    extra_direct: List[str] = list(warm.get('subs') or [])
                    t_link = time.monotonic() - t_ep
                    log.cprint(f'load: ep{ep.num} from prefetched file '
                               f'({os.path.getsize(url) // 1048576}MB)')
                    stream = None
                else:
                    stream = self.provider.stream(ep.num)
                    name = self._name(ep, stream)
                    direct = getattr(stream, 'direct', False)
                    extra_direct: List[str] = []
                    head_warm = False
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
                        # brief head peek only - then start: the prewarm keeps
                        # filling the head in the background and the proxy
                        # live-reads any gap mpv asks for in the meantime
                        head_warm = ready.wait(2)
                        url = self.proxy.url(name)
                        t_link = time.monotonic() - t_ep   # incl. head warm-up
                    t_link = time.monotonic() - t_ep
                    log.cprint(f'load: ep{ep.num} link + head peek in '
                               f'{t_link:.1f}s ({"hls" if direct else "proxy"})')
                # chapters come from the origin first, this proxy as fallback;
                # a failed head peek must not leave this list empty (dead skip)
                targets = probe_targets(stream, None if direct else url)

                if 'flags' not in warm:
                    if self.skip is not None:
                        t_sk = time.monotonic()
                        try:
                            flags, note = self.skip.flags(
                                title=title, ep=ep.num, targets=targets,
                                mode=skip_mode,
                                toggle=skip_toggle, timeout=6,
                                mal_id=self.mal_id or getattr(
                                    self.provider, 'mal_id', None))
                        except Exception as ex:
                            flags, note = [], f'failed ({ex})'
                        log.cprint(f'skip[{skip_mode}]: {note} '
                                   f'in {time.monotonic() - t_sk:.1f}s')
                else:
                    log.cprint(f'skip[{skip_mode}]: {note} (prefetched)')


                sock = f'/tmp/tgplay-{os.getpid()}-{ep.num}.ipc'
                ep_end = end if i == 0 else None      # ep 1 only, like start
                fire = None
                on_fire = None
                if next_frac and nxt is not None and self.prefetcher is not None \
                        and os.environ.get('AGP_NO_WARM', '') not in ('1', 'yes'):
                    fire = self._trigger(cut, next_frac, ep_end)

                    def on_fire(_nxt=nxt):
                        threading.Thread(target=self._warm, args=(_nxt,),
                                         daemon=True).start()

                fired = [False]
                seeked = [False]

                def _tick(p, _n=ep.num):
                    if not fired[0]:
                        fired[0] = True
                        log.cprint(f'mpv: ep{_n} window up in '
                                   f'{time.monotonic() - t_ep:.1f}s')
                    if not seeked[0]:
                        seeked[0] = True
                        s0 = ep_start if isinstance(ep_start, int) else None
                        if s0 and _behind(p, s0) and ipc_seek(sock, s0):
                            log.cprint(f'start: mpv opened at {int(p)}s, '
                                       f'seeked ep{_n} to {s0}s')
                    self._on_pos(title, _n, p, getattr(watcher, 'duration', 0))

                watcher = PosWatcher(
                    sock, self.interval,
                    on_pos=_tick,
                    fire_when=fire, on_fire=on_fire)
                self._pause_at = 0.0
                ep_start = start if i == 0 else None
                if i == 0 and ep_start is None:
                    ep_start = self._resume_point(ep.num)
                if i == 0 and ep_start is not None:
                    if not isinstance(ep_start, str):
                        log.cprint(f'start: ep{ep.num} at {int(ep_start)}s')
                elif i == 0:
                    log.cprint(f'start: ep{ep.num} at 0s (no saved position)')
                if ep_end is not None and isinstance(ep_start, int) \
                        and ep_end <= ep_start:
                    # mpv would open and exit at once; play normally instead
                    log.cprint(f'end: ignored, {int(ep_end)}s is not after '
                               f'start {int(ep_start)}s')
                    ep_end = None
                if ep_end is not None:
                    log.cprint(f'end: ep{ep.num} at {int(ep_end)}s')
                watcher.start()
                self._scrobble('start', ep.num, 0)
                cmd = self.player.command(
                    url, title=name, extra=(list(extra or []) + extra_direct + flags),
                    start=ep_start, cut=cut, end=ep_end, ipc=sock)
                tag = (f'  [start {ep_start}s]' if isinstance(ep_start, int)
                       else f'  [start {ep_start}]' if ep_start else '')
                if ep_end is not None:
                    tag += f'  [end {ep_end}s]'
                elif cut:
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

    def _on_pos(self, title, num, pos, dur=0.0):
        """Save locally every tick, and push a Simkl pause every PAUSE_EVERY
        seconds so the resume point outlives a crash or a second device."""
        self._save(title, num, pos)
        if dur and pos - self._pause_at >= PAUSE_EVERY:
            self._pause_at = pos
            self._scrobble('pause', num, pos / dur * 100)

    def _resume_point(self, num):
        """Start position for ep `num` from Simkl (another device) when the
        local progress file has none: '42%' for mpv, or None."""
        fn = getattr(self.tracker, 'resume', None)
        if fn is None:
            return None
        mal = self.mal_id or getattr(self.provider, 'mal_id', None)
        anilist = getattr(self.provider, 'anilist_id', None)
        try:
            r = fn(self.provider.title, num, mal=mal, anilist=anilist)
        except Exception:
            return None
        pct = float((r or {}).get('percent') or 0)
        if not 0 < pct < 95:      # 0 = nothing saved; >=95 = already finished
            return None
        log.cprint(f'resume: ep{num} at {pct:.0f}% (Simkl, another device)')
        return f'{pct:.0f}%'

    def _scrobble(self, action, num, progress):
        """Report playback progress (start / pause / stop) from a worker
        thread: a slow API must never hold up mpv."""
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
            forget = getattr(self.tracker, 'forget', None)
            if forget is not None:      # local watch outran Simkl's resume point
                _safe(forget, self.provider.title, num, mal=mal,
                      anilist=anilist)
        threading.Thread(target=work, daemon=True).start()
