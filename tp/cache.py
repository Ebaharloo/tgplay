"""tp.cache - on-disk mirror bookkeeping + LRU eviction.

One place owns the cache directory, the mirror sidecars (`.done`/`.win`/
`.part`) and eviction, so `agp` and the proxy stop each carrying half of it.
"""
import json
import os
import re
from typing import Dict, Iterable, Optional

_SUFFIX = re.compile(r'\.(mkv|part|done|win|full|aria2|aria2\.h|part\.aria2)$')
DEFAULT_BUDGET = 2 * 1024 * 1024 * 1024  # /tmp is tmpfs (RAM)


class Cache:
    def __init__(self, directory: str, budget: int = DEFAULT_BUDGET):
        self.dir = directory
        self.budget = budget

    def ensure(self):
        os.makedirs(self.dir, exist_ok=True)
        return self

    # --- paths -------------------------------------------------------------
    def path(self, name: str) -> str:
        self.ensure()
        return f'{self.dir}/{re.sub(r"[^A-Za-z0-9._-]", "_", name)}'

    def done(self, name): return self.path(name) + '.done'
    def part(self, name): return self.path(name) + '.part'
    def win(self, name): return self.path(name) + '.win'

    # --- mirror geometry ---------------------------------------------------
    def geometry(self, name: str) -> Optional[dict]:
        try:
            return json.load(open(self.done(name)))
        except Exception:
            return None

    def set_geometry(self, name: str, lo: int, size: int,
                     length: Optional[int] = None):
        d = {'lo': lo, 'size': size}
        if length is not None:
            d['len'] = length
        json.dump(d, open(self.done(name), 'w'))
        return d

    def is_full(self, name: str) -> bool:
        """A mirror that covers byte 0 .. size (safe to serve as a whole)."""
        g = self.geometry(name)
        if not g or g.get('lo') != 0 or not g.get('size'):
            return False
        return g.get('len') is None or g.get('len') == g.get('size')

    # --- eviction ----------------------------------------------------------
    def evict(self, keep: Iterable[str] = ()):
        """Delete oldest-mtime families until under budget (LRU)."""
        try:
            files = [os.path.join(self.dir, f) for f in os.listdir(self.dir)]
        except OSError:
            return
        keep = tuple(keep)
        entries: Dict[str, dict] = {}
        total = 0
        for p in files:
            if not os.path.isfile(p):
                continue
            base = p
            while True:  # strip the whole suffix chain: name.mkv.done -> name
                b = _SUFFIX.sub('', base)
                if b == base:
                    break
                base = b
            e = entries.setdefault(base, {'files': [], 'bytes': 0, 'mtime': 0})
            e['files'].append(p)
            try:
                st = os.stat(p)
            except OSError:
                continue
            e['bytes'] += st.st_size
            e['mtime'] = max(e['mtime'], st.st_mtime)
            total += st.st_size
        for base, e in sorted(entries.items(), key=lambda kv: kv[1]['mtime']):
            if total <= self.budget:
                break
            if any(k == base or k.startswith(base + '.') for k in keep):
                continue  # never evict a file in use
            for p in e['files']:
                try:
                    os.remove(p)
                except OSError:
                    pass
            total -= e['bytes']
