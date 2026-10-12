"""tp.history - recent links and search queries for the launcher.

Kept next to the other state (next to progress.json) as `history.json`:
    {"links": [{"link", "ts", "source"}, ...newest first...],
     "queries": [...]}

Links carry the time they were opened (unix ts) and their source id, so the
GUI can show "when + where + what" per row. Plain strings from older files
are migrated on load as ts=0 (shown as an unknown/old date at the bottom).
"""
import json
import os
import time
from typing import List

LIMIT = 20


def _path(cfg) -> str:
    return os.path.join(os.path.dirname(cfg.progress), 'history.json')


def _source_of(link: str) -> str:
    """Best-effort source id for a link (for display only)."""
    try:
        from .cli_all import route
        r = route(link)
        return r[0] if r else 'link'
    except Exception:
        return 'link'


def _load(cfg) -> dict:
    try:
        d = json.load(open(_path(cfg)))
    except Exception:
        d = {}
    links: List[dict] = []
    for x in (d.get('links') or []):
        if isinstance(x, dict) and x.get('link'):
            links.append({'link': str(x['link']),
                          'ts': int(x.get('ts') or 0),
                          'source': str(x.get('source') or '')})
        elif isinstance(x, str) and x.strip():          # old format: migrate
            links.append({'link': x.strip(), 'ts': 0, 'source': ''})
    queries = [str(q) for q in (d.get('queries') or []) if str(q).strip()]
    return {'links': links, 'queries': queries}


def _save(cfg, d) -> None:
    try:
        os.makedirs(os.path.dirname(_path(cfg)), exist_ok=True)
        json.dump(d, open(_path(cfg), 'w'))
    except Exception:
        pass


def add(cfg, *, link: str = None, query: str = None, source: str = None,
        limit: int = LIMIT) -> None:
    """Record a link/query as just-opened (moves to the top, sets the time)."""
    if link:
        link = str(link).strip()
    if query:
        query = str(query).strip()
    if not link and (not query or not query.strip()):
        return
    d = _load(cfg)
    if link:
        d['links'] = [{'link': link,
                       'ts': int(time.time()),
                       'source': source or _source_of(link)}] \
            + [x for x in d['links'] if x['link'] != link]
        d['links'] = d['links'][:limit]
    if query:
        d['queries'] = [query] + [q for q in d['queries'] if q != query]
        d['queries'] = d['queries'][:limit]
    _save(cfg, d)


def remove(cfg, *, link: str = None, query: str = None) -> None:
    """Delete one link/query from the history (the ✕ button)."""
    d = _load(cfg)
    if link:
        d['links'] = [x for x in d['links'] if x['link'] != str(link)]
    if query:
        d['queries'] = [q for q in d['queries'] if q != str(query)]
    _save(cfg, d)


def recent(cfg, limit: int = 15) -> List[dict]:
    """Combined list for the picker: links (newest first), then past queries.

    Each item: {'title', 'url' (None for a query), 'source', 'kind', 'ts'}.
    """
    d = _load(cfg)
    out: List[dict] = []
    for e in d['links'][:limit]:
        src = e.get('source') or _source_of(e['link'])
        out.append({'title': e['link'], 'url': e['link'], 'source': src,
                    'kind': 'link', 'ts': e.get('ts') or 0})
    for q in d['queries'][:limit]:
        out.append({'title': q, 'url': None, 'source': 'recent search',
                    'kind': 'query', 'ts': 0})
    return out[:limit]
