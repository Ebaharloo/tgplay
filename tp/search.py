"""tp.search - one search box, both sources (used by the desktop menus).

Keeps the GUI provider-agnostic: it just calls a `search_fn(query)` that
returns `[{'title', 'url', 'source'}]`, when `source` is `agp` or `axp`.
"""
from typing import List, Sequence


def search_all(query: str, http=None, sources: Sequence[str] = ('agp', 'axp'),
               limit: int = 12) -> List[dict]:
    q = (query or '').strip()
    if not q:
        return []
    out: List[dict] = []
    if 'agp' in sources:
        try:
            from .providers.animegate import search as ag
            out += ag(q, http=http, limit=limit)
        except Exception:
            pass
    if 'axp' in sources:
        try:
            from .providers.animex import search as ax
            out += ax(q, http=http, limit=limit)
        except Exception:
            pass
    return out
