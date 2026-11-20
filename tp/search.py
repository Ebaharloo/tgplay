"""tp.search - one search box, every source (used by the desktop menus).

Keeps the GUI provider-agnostic: it calls the per-source Search feature
objects, which return `[{'title', 'url', 'source'}]` each.
"""
from typing import List, Sequence

from .features import get


def search_all(query: str, http=None,
               sources: Sequence[str] = ('agp', 'axp', 'zoro'),
               limit: int = 12) -> List[dict]:
    q = (query or '').strip()
    if not q:
        return []
    out: List[dict] = []
    for src in sources:
        cls = get(src, 'search')
        if cls is None:                     # tg/tgp: no title search
            continue
        try:
            out += cls().search(q, http=http, limit=limit)
        except Exception:
            pass                            # one down source hides the rest
    return out
