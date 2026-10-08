"""tp.prefetch - background mirroring of an episode into the Cache.

Downloads a (window of a) `MediaSource` to the cache so the next play reads
from disk. Cancellable per name via a `threading.Event`, so "download keeps
running after the player closed" cannot happen. aria2 is a fast path when
available; the portable path uses the source's own ranged reads.
"""
import json
import os
import shutil
import subprocess
import threading
from typing import Callable, Dict, Optional

HEAD = 8 * 1024 * 1024
TAIL = 2 * 1024 * 1024
CHUNK = 16 * 1024 * 1024


class Prefetcher:
    def __init__(self, cache, chunk: int = CHUNK, aria2: bool = False):
        self.cache = cache
        self.chunk = chunk
        self.aria2 = aria2
        self._stops: Dict[str, threading.Event] = {}
        self._procs = set()
        self._lock = threading.Lock()

    # --- lifecycle ---------------------------------------------------------
    def stop_event(self, name: str) -> threading.Event:
        return self._stops.setdefault(name, threading.Event())

    def cancel(self, name: str):
        self.stop_event(name).set()

    def active(self, name: str) -> bool:
        return not self.stop_event(name).is_set()

    def kill_all(self):
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass

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
            return path
        if stop.is_set():
            return None
        total = source.size
        if not total:
            return None
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
            return path
        return None
