"""tp.chapters - intro/outro detection -> mpv `--script-opts` for skip.lua.

Precedence: explicitly NAMED chapters win ('Intro'/'Opening', 'Credits'/
'Ending'...). A positional guess (a short leading/trailing chapter around the
longest 'main' chapter) only fills a side the names did not cover -- so a
donghua named 'Chapter 1'/'Ending Song' still works, but a real named chapter
is never overridden.

mode: 'all' = names then positional fallback (default)
      'names' = named chapters only
      'auto'  = positional guess only
"""
import json
import re
import subprocess
from typing import List, NamedTuple, Optional, Tuple

OP_RE = re.compile(r'(?:^|\W)(op|opening|intro|introduction)(?:\W|\d|$)', re.I)
ED_RE = re.compile(r'(?:^|\W)(ed|ending|end|outro|credits?|creditless)(?:\W|\d|$)', re.I)

Side = Optional[Tuple[float, float]]


class Chapter(NamedTuple):
    title: str
    start: float
    end: float


class SkipResolver:
    def __init__(self, ffprobe='ffprobe', timeout=30):
        self.ffprobe = ffprobe
        self.timeout = timeout

    # --- classification ----------------------------------------------------
    @staticmethod
    def kind(title: Optional[str]) -> Optional[str]:
        t = (title or '').strip()
        if OP_RE.search(t):
            return 'op'
        if ED_RE.search(t):
            return 'ed'
        return None

    # --- decision ----------------------------------------------------------
    @staticmethod
    def _decide(chapters, mode='all'):
        """(op, ed, op_src, ed_src) - src is 'named' | 'positional' | None."""
        op = ed = None
        osrc = esrc = None
        if mode != 'auto':  # trust explicit titles
            for c in chapters:
                k = SkipResolver.kind(c[0])
                if k == 'op' and op is None:
                    op, osrc = (c[1], c[2]), 'named'
                elif k == 'ed' and ed is None:
                    ed, esrc = (c[1], c[2]), 'named'
        if mode == 'names' or len(chapters) < 2:
            return op, ed, osrc, esrc
        # positional fallback for a side the names did not provide
        main = max(chapters, key=lambda c: c[2] - c[1])
        mlen = main[2] - main[1]

        def short(c):
            d = c[2] - c[1]
            return 0 < d <= 0.25 * mlen and d <= 180

        leading = [c for c in chapters if c[2] <= main[1] + 1 and short(c)]
        trailing = [c for c in chapters if c[1] >= main[2] - 1 and short(c)]
        if op is None and leading and (ed is not None or trailing):
            op, osrc = (min(c[1] for c in leading), main[1]), 'positional'
        if ed is None and trailing:
            ed, esrc = (main[2], max(c[2] for c in trailing)), 'positional'
        return op, ed, osrc, esrc

    @staticmethod
    def to_skip(chapters, mode='all'):
        op, ed, _os, _es = SkipResolver._decide(chapters, mode)
        return op, ed

    def resolve(self, url: str, mode: str = 'all', timeout=None):
        """(op, ed, op_src, ed_src) from the file's own chapters."""
        return self._decide(self.probe(url, timeout), mode)

    # --- ffprobe -----------------------------------------------------------
    def probe(self, url: str, timeout: Optional[float] = None) -> List[Chapter]:
        try:
            r = subprocess.run(
                [self.ffprobe, '-v', 'quiet', '-print_format', 'json',
                 '-show_chapters', url],
                capture_output=True, text=True, timeout=timeout or self.timeout)
            raw = json.loads(r.stdout or '{}').get('chapters', [])
        except Exception:
            return []
        out = []
        for c in raw:
            try:
                out.append(Chapter((c.get('tags') or {}).get('title'),
                                   float(c['start_time']), float(c['end_time'])))
            except (KeyError, TypeError, ValueError):
                continue
        return out

    # --- output ------------------------------------------------------------
    @staticmethod
    def opts_from(op: Side, ed: Side, toggle: bool = False) -> List[str]:
        parts = []
        if op:
            parts += [f'skip-op_start={op[0]}', f'skip-op_end={op[1]}']
        if ed:
            parts += [f'skip-ed_start={ed[0]}', f'skip-ed_end={ed[1]}']
        if parts and toggle:
            parts += ['skip-toggle=yes', 'skip-toggle_key=T']
        return ['--script-opts=' + ','.join(parts)] if parts else []

    def flags(self, url: str, mode: str = 'all', toggle: bool = False,
              timeout: Optional[float] = None) -> List[str]:
        op, ed = self.to_skip(self.probe(url, timeout), mode)
        return self.opts_from(op, ed, toggle)
