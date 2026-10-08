"""tp.cache - on-disk mirror bookkeeping + LRU eviction.

One place owns the cache directory, the mirror sidecars (`.done`/`.win`/
`.part`) and eviction, so `agp` and the proxy stop each carrying half of it.
"""
import json
import os
import re
import time
from typing import Dict, Iterable, List, Optional

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

    # --- report / explicit cleanup -----------------------------------------
    def report(self) -> List[dict]:
        """One row per cached family: size, age, and whether it is unfinished."""
        try:
            files = [os.path.join(self.dir, f) for f in os.listdir(self.dir)]
        except OSError:
            return []
        fam: Dict[str, dict] = {}
        for p in files:
            if not os.path.isfile(p):
                continue
            base = p
            while True:
                b = _SUFFIX.sub('', base)
                if b == base:
                    break
                base = b
            e = fam.setdefault(base, {'files': [], 'bytes': 0, 'mtime': 0,
                                      'partial': False})
            e['files'].append(p)
            try:
                st = os.stat(p)
            except OSError:
                continue
            e['bytes'] += st.st_size
            e['mtime'] = max(e['mtime'], st.st_mtime)
            if '.part' in os.path.basename(p):
                e['partial'] = True
        now = time.time()
        out = []
        for base, e in sorted(fam.items(), key=lambda kv: kv[1]['mtime']):
            disp = None
            for f in e['files']:
                b = os.path.basename(f)
                if not b.endswith(('.done', '.win', '.aria2', '.part')):
                    disp = b
                    break
            if disp is None:
                disp = os.path.basename(e['files'][0])
            disp = re.sub(r'\.(done|win|aria2|part)$', '', disp)
            out.append({'name': disp, 'bytes': e['bytes'],
                        'age_days': (now - e['mtime']) / 86400.0,
                        'partial': e['partial'], 'files': e['files']})
        return out

    def clean(self, days: float = 3.0, include_partials: bool = True,
              all: bool = False) -> int:
        """Delete cached families older than `days` (or everything with
        `all=True`). Unfinished downloads are kept when include_partials=False,
        so a viewer who will continue another day does not lose progress."""
        removed = 0
        for e in self.report():
            if not all and e['age_days'] < days:
                continue
            if e['partial'] and not include_partials:
                continue
            for p in e['files']:
                try:
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
        return removed

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
