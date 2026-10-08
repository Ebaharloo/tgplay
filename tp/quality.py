"""tp.quality - derive quality from filenames.

Telegram playlists have no quality *groups* like animegate, so we reconstruct
the same choice from the file names ('480p', '720p', '1080p', '2160p'/'4K').
Files that are identical once the quality token is removed are variants of the
same episode.
"""
import re
from typing import Dict, List, Optional, Tuple

_Q = re.compile(r'(?<![A-Za-z0-9])(\d{3,4})\s*[pP](?![A-Za-z])'
                r'|(?<![A-Za-z0-9])(4K|2160P?)(?![A-Za-z0-9])', re.I)


def parse_quality(name: str) -> Optional[str]:
    """'...480p...' -> '480p'; '...4K...' -> '2160p'; None if unknown."""
    m = _Q.search(name or '')
    if not m:
        return None
    tok = m.group(0).lower().replace(' ', '')
    if tok in ('4k', '2160', '2160p'):
        return '2160p'
    return tok


def _res(q: str) -> int:
    m = re.search(r'\d+', q or '')
    return int(m.group(0)) if m else 0


def strip_quality(name: str) -> str:
    """The file name with the quality token removed (the 'episode key')."""
    return re.sub(r'\s+', ' ', _Q.sub('', name or '')).strip()


def group(names: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    """(qualities ascending, {quality: [names]}), or ([], {}) when there is
    only one (or no) quality so the caller keeps the flat list."""
    quals = []
    for n in names:
        q = parse_quality(n)
        if q and q not in quals:
            quals.append(q)
    quals = sorted(quals, key=_res)
    if len(quals) < 2:
        return [], {}
    byq: Dict[str, List[str]] = {q: [] for q in quals}
    other = []
    for n in names:
        q = parse_quality(n)
        (byq[q] if q in byq else other).append(n)
    for q in quals:
        byq[q] = byq[q] + other  # untagged files offered in every group
    return quals, byq
