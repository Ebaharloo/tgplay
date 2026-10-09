"""tp.history - recent links and search queries for the launcher.

Kept next to the other state (next to progress.json) as `history.json`:
    {"links": [...newest first...], "queries": [...]}
"""
import json
import os
from typing import List

LIMIT = 20


def _path(cfg) -> str:
    return os.path.join(os.path.dirname(cfg.progress), 'history.json')


def _load(cfg) -> dict:
    try:
        d = json.load(open(_path(cfg)))
    except Exception:
        d = {}
    return {'links': list(d.get('links') or []),
            'queries': list(d.get('queries') or [])}


def _save(cfg, d) -> None:
    try:
        os.makedirs(os.path.dirname(_path(cfg)), exist_ok=True)
        json.dump(d, open(_path(cfg), 'w'))
    except Exception:
        pass


def add(cfg, *, link: str = None, query: str = None, limit: int = LIMIT) -> None:
    d = _load(cfg)
    if link:
        d['links'] = [link] + [x for x in d['links'] if x != link]
    if query:
        d['queries'] = [query] + [x for x in d['queries'] if x != query]
    d['links'] = d['links'][:limit]
    d['queries'] = d['queries'][:limit]
    _save(cfg, d)


def recent(cfg, limit: int = 15) -> List[dict]:
    """Combined list for the picker: links first, then past queries.

    Each item: {'title', 'url' (None for a query), 'source', 'kind'}.
    """
    d = _load(cfg)
    out: List[dict] = []
    for link in d['links'][:limit]:
        src = 'agp'
        try:
            from .cli_all import route
            r = route(link)
            if r:
                src = r[0]
        except Exception:
            pass
        out.append({'title': link, 'url': link, 'source': src, 'kind': 'link'})
    for q in d['queries'][:limit]:
        out.append({'title': q, 'url': None, 'source': 'recent',
                    'kind': 'query'})
    return out[:limit]
