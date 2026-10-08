"""tp.skip - intro/outro skip flags, with a human note of WHAT was applied.

Order: the mkv's OWN chapters first (see tp.chapters), then ani-skip
(aniskip.com) when the file carries nothing. `flags()` returns
`(mpv_args, note)` where note says which detector ran and the times, so the
log shows exactly why a jump happened.
"""
import re
import shutil
import subprocess
from typing import List, Optional, Tuple

from .chapters import SkipResolver


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


class AniSkip:
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
            r = subprocess.run(args, capture_output=True, text=True, timeout=60)
        except Exception:
            return None
        out = (r.stdout or '').strip()
        if not out:
            return []
        return [t for t in out.split() if t.startswith('--')]


class SkipService:
    def __init__(self, resolver: Optional[SkipResolver] = None,
                 ani_skip: Optional[AniSkip] = None, metadata=None):
        self.chapters = resolver or SkipResolver()
        self.ani = ani_skip or AniSkip()
        self.meta = metadata

    def flags(self, *, title: str, ep: int, url: Optional[str] = None,
              mode: str = 'all', toggle: bool = False,
              timeout: float = 30) -> Tuple[List[str], str]:
        """(mpv args, note). note names the detector + times applied."""
        if url:
            op, ed, osrc, esrc = self.chapters.resolve(url, mode, timeout)
            f = self.chapters.opts_from(op, ed, toggle)
            if f:
                return f, _chapter_note(op, ed, osrc, esrc)
        mal = None
        if self.meta is not None:
            mal = self.meta.resolve_mal(title, ask=False)
        if mal is None or not self.ani.available():
            return [], 'none (no usable chapters, no ani-skip data)'
        af = self.ani.flags(mal, ep, toggle) or []
        return af, (_ani_note(af) if af else 'none (ani-skip has no data)')
