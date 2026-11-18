"""tp.prefetch - background mirroring of an episode into the Cache.

Downloads a (window of a) `MediaSource` to the cache so the next play reads
from disk. Cancellable per name via a `threading.Event`, so "download keeps
running after the player closed" cannot happen. aria2 is a fast path when
available; the portable path uses the source's own ranged reads.
"""
import json
import os
import threading
import time
from typing import Callable, Dict, Optional

from . import log

HEAD = 8 * 1024 * 1024
TAIL = 2 * 1024 * 1024
CHUNK = 16 * 1024 * 1024


class Prefetcher:
    def __init__(self, cache, chunk: int = CHUNK, aria2: bool = False):
        self.cache = cache
        self.chunk = chunk
        self.aria2 = aria2
        self._stops: Dict[str, threading.Event] = {}

    # --- lifecycle ---------------------------------------------------------
    def stop_event(self, name: str) -> threading.Event:
        return self._stops.setdefault(name, threading.Event())

    def cancel(self, name: str):
        self.stop_event(name).set()

    def active(self, name: str) -> bool:
        return not self.stop_event(name).is_set()

    def publish(self, proxy, name: str, path: str) -> int:
        """Hand a finished download window to the proxy: the next play of this
        episode then reads bytes from disk instead of the CDN."""
        try:
            win = json.load(open(path + '.win'))
        except Exception:
            win = {}
        size, lo = int(win.get('size') or 0), int(win.get('lo') or 0)
        proxy.set_local(name, path, size, lo=lo, live=True)
        return lo

    def complete(self, name: str) -> bool:
        return self.cache.is_full(name) and os.path.exists(self.cache.path(name))

    # --- work --------------------------------------------------------------
    def prefetch(self, name: str, source, lo_f: float = 0.0, hi_f: float = 1.0,
                 on_progress: Optional[Callable[[int, int], None]] = None
                 ) -> Optional[str]:
        path = self.cache.path(name)
        part = path + '.part'
        stop = self.stop_event(name)
        if self.complete(name):
            log.cprint(f'download: {name} already cached')
            return path
        if stop.is_set():
            return None
        total = source.size
        if not total:
            return None
        t0 = time.monotonic()
        lo = min(int(total * lo_f), max(total - TAIL, 0))
        hi = max(int(total * hi_f), HEAD)
        lo, hi = max(lo - HEAD, 0), min(hi + TAIL, total)
        want = hi - lo
        json.dump({'lo': lo, 'size': total}, open(path + '.win', 'w'))
        got = os.path.getsize(part) if os.path.exists(part) else 0
        if got > want:
            got = 0
        try:
            with open(part, 'ab' if got else 'wb') as f:
                pos = lo + got
                while pos < hi:
                    if stop.is_set():
                        return None
                    buf = source.read(pos, min(pos + self.chunk, hi))
                    if not buf:
                        break
                    f.write(buf)
                    f.flush()
                    pos += len(buf)
                    got += len(buf)
                    if on_progress:
                        on_progress(got, want)
        except Exception:
            return None  # keep .part for resume
        if got >= want and not stop.is_set():
            os.replace(part, path)
            self.cache.set_geometry(name, lo, total, got)
            log.cprint(f'download: {name} · {got // 1048576}MB in '
                       f'{time.monotonic() - t0:.0f}s')
            return path
        return None


def hls_to_file(url: str, headers: Optional[Dict[str, str]], out: str,
                stop: Optional[threading.Event] = None) -> bool:
    """Pull an HLS stream to `out` with ffmpeg (stream copy, no re-encode).

    Direct (HLS/DASH) sources have no `size`, so the byte reader cannot mirror
    them - but ffmpeg can, and a local file makes mpv open instantly instead
    of buffering a cold CDN stream."""
    import shutil
    import subprocess
    ff = shutil.which('ffmpeg')
    if not ff or (stop is not None and stop.is_set()):
        return False
    h = headers or {} if url.startswith('http') else {}
    part = out + '.part'
    cmd = [ff, '-nostdin', '-loglevel', 'error', '-y']
    if h.get('Referer'):
        cmd += ['-referer', h['Referer']]
    if h.get('User-Agent'):
        cmd += ['-user_agent', h['User-Agent']]
    cmd += ['-i', url, '-c', 'copy', '-f', 'matroska', part]
    try:
        rc = subprocess.run(cmd, timeout=3600).returncode
    except Exception as ex:
        log.cprint(f'prefetch: ffmpeg failed ({ex})')
        return False
    if rc != 0 or not os.path.exists(part) or os.path.getsize(part) < 1024:
        log.cprint(f'prefetch: ffmpeg gave up on {os.path.basename(out)}')
        return False
    os.replace(part, out)
    return True
