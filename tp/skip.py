"""tp.skip - intro/outro skip, split so one failed probe cannot kill it.

Four objects, one job each:
  ChapterReader   ffprobe -> list[Chapter]                  (tp.chapters, I/O)
  SkipDecider     chapters + mode -> op/ed/why              (pure, no I/O)
  AniSkipRunner   the ani-skip binary only
  SkipService     probe targets in order, then ani-skip; builds the note

`probe_targets(stream, proxy_url)` says where to read chapters for a stream
(origin first, our range proxy second) - the playlist calls it once and hands
the list to `SkipService.flags()`. `flags()` keeps its old keyword signature;
it returns `(mpv_args, note)` and the note names the detector + times.
"""
import re
import shutil
import subprocess
from typing import List, Optional, Tuple

from .chapters import ChapterReader

Side = Optional[Tuple[float, float]]


def _mmss(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    m, s = divmod(int(v), 60)
    h, m = divmod(m, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def _span(seg) -> str:
    return f'{_mmss(seg[0])}-{_mmss(seg[1])}' if seg else ''


def _chapter_note(op, ed, osrc, esrc) -> str:
    src = osrc if osrc == esrc else ('mixed' if (osrc or esrc) else '?')
    parts = []
    if op:
        parts.append(f'op {_span(op)}')
    if ed:
        parts.append(f'ed {_span(ed)}')
    return f'chapters({src}) · ' + ' · '.join(parts)


def _ani_note(flags) -> str:
    blob = ' '.join(flags)

    def val(k):
        m = re.search(rf'{k}=([0-9.]+)', blob)
        return m.group(1) if m else None

    op = (val('skip-op_start'), val('skip-op_end'))
    ed = (val('skip-ed_start'), val('skip-ed_end'))
    parts = []
    if op[0] and op[1]:
        parts.append(f'op {_mmss(op[0])}-{_mmss(op[1])}')
    if ed[0] and ed[1]:
        parts.append(f'ed {_mmss(ed[0])}-{_mmss(ed[1])}')
    return 'ani-skip' + (' · ' + ' · '.join(parts) if parts else '')


def probe_targets(stream, proxy_url: Optional[str] = None
                  ) -> List[Tuple[Optional[str], Optional[dict]]]:
    """[(url, headers), ...] to read chapters from: the origin, then the proxy.

    The origin answers with cheap plain ranges; the proxy is the same bytes we
    already serve, so it answers when the origin hides its chapters.
    """
    url = getattr(stream, 'url', None)
    if not url:
        return []
    headers = getattr(stream, 'headers', None) or None
    out = [(url, headers)]
    if proxy_url and proxy_url != url:
        out.append((proxy_url, None))
    return out


class SkipDecider:
    """chapters + mode -> (op, ed, op_src, ed_src). No I/O.

    Named chapters win ('Intro'/'Opening', 'Credits'/'Ending'...); a positional
    guess (short leading/trailing chapter around the longest 'main' chapter)
    only fills a side the names did not cover.
    mode: 'all' = names then guess, 'names' = names only, 'auto' = guess only.
    """
    OP_RE = re.compile(r'(?:^|\W)(op|opening|intro|introduction)(?:\W|\d|$)', re.I)
    ED_RE = re.compile(r'(?:^|\W)(ed|ending|end|outro|credits?|creditless)(?:\W|\d|$)', re.I)

    @classmethod
    def kind(cls, title: Optional[str]) -> Optional[str]:
        t = (title or '').strip()
        if cls.OP_RE.search(t):
            return 'op'
        if cls.ED_RE.search(t):
            return 'ed'
        return None

    @classmethod
    def decide(cls, chapters, mode: str = 'all'):
        """(op, ed, op_src, ed_src) - src is 'named' | 'positional' | None."""
        op = ed = None
        osrc = esrc = None
        if mode != 'auto':  # trust explicit titles
            for c in chapters:
                k = cls.kind(c[0])
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

    @classmethod
    def to_skip(cls, chapters, mode: str = 'all'):
        op, ed, _os, _es = cls.decide(chapters, mode)
        return op, ed

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


class AniSkipRunner:
    def __init__(self, binary: str = 'ani-skip'):
        self.binary = binary

    def available(self) -> bool:
        return bool(shutil.which(self.binary))

    def flags(self, mal_id: int, ep: int, toggle: bool = False
              ) -> Optional[List[str]]:
        """[] when ani-skip has no data, None when it is unavailable."""
        if not self.available():
            return None
        args = [self.binary, '-i', str(mal_id), '-e', str(ep)]
        if toggle:
            args.append('--toggle')
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=15)
        except Exception:
            return None
        out = (r.stdout or '').strip()
        if not out:
            return []
        return [t for t in out.split() if t.startswith('--')]


class SkipService:
    def __init__(self, reader: Optional[ChapterReader] = None,
                 decider: Optional[SkipDecider] = None,
                 ani_skip: Optional[AniSkipRunner] = None, metadata=None):
        self.reader = reader or ChapterReader()
        self.decider = decider or SkipDecider()
        self.ani = ani_skip or AniSkipRunner()
        self.meta = metadata

    def flags(self, *, title: str, ep: int, url: Optional[str] = None,
              mode: str = 'all', toggle: bool = False,
              timeout: float = 30, mal_id: Optional[int] = None,
              headers: Optional[dict] = None,
              url2: Optional[str] = None,
              targets: Optional[List[Tuple[Optional[str], Optional[dict]]]] = None
              ) -> Tuple[List[str], str]:
        """(mpv args, note). note names the detector + times applied.

        `targets` is the candidate list from `probe_targets()`; the `url`/
        `url2` keywords still work and mean the same two candidates. A slow or
        header-guarded origin must not silently kill skip.
        """
        if mode == 'off':
            return [], 'off'
        if targets is None:
            targets = [(url, headers)] + ([(url2, None)] if url2 else [])
        for target, hdrs in targets:
            if not target:
                continue
            try:
                chapters = self.reader.read(target, headers=hdrs,
                                            timeout=timeout)
            except Exception:      # a dead reader must not stop the next one
                continue
            op, ed, osrc, esrc = self.decider.decide(chapters, mode)
            f = self.decider.opts_from(op, ed, toggle)
            if f:
                return f, _chapter_note(op, ed, osrc, esrc)
        mal = mal_id
        if mal is None and self.meta is not None:
            mal = self.meta.resolve_mal(title, ask=False)
        if mal is None or not self.ani.available():
            return [], 'none (no usable chapters, no ani-skip data)'
        af = self.ani.flags(mal, ep, toggle) or []
        return af, (_ani_note(af) if af else 'none (ani-skip has no data)')
