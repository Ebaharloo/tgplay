"""tp.history - recent links and search queries for the launcher.

Kept next to the other state (next to progress.json) as `history.json`:
    {"links": [{"link", "ts", "source", "name"}, ...newest first...],
     "queries": [...]}

Links carry the time they were opened (unix ts), their source id and the
SHOW NAME (filled once the session loads) so the UI shows anime names, not
raw URLs. Plain strings from older files are migrated on load as ts=0
(shown as an unknown/old date at the bottom).
"""
import json
import os
import time
from typing import List, Optional

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
                          'source': str(x.get('source') or ''),
                          'name': str(x.get('name') or '')})
        elif isinstance(x, str) and x.strip():          # old format: migrate
            links.append({'link': x.strip(), 'ts': 0, 'source': '',
                          'name': ''})
    queries = [str(q) for q in (d.get('queries') or []) if str(q).strip()]
    return {'links': links, 'queries': queries}


def _save(cfg, d) -> None:
    try:
        from .config import save_json
        save_json(_path(cfg), d)
    except Exception:
        pass


def add(cfg, *, link: str = None, query: str = None, source: str = None,
        name: str = None, limit: int = LIMIT) -> None:
    """Record a link/query as just-opened (moves to the top, sets the time).

    `name` stores the show title so the picker can display anime names
    instead of raw links."""
    if link:
        link = str(link).strip()
    if query:
        query = str(query).strip()
    if not link and (not query or not query.strip()):
        return
    d = _load(cfg)
    if link:
        old = next((x for x in d['links'] if x['link'] == link), None)
        d['links'] = [{'link': link,
                       'ts': int(time.time()),
                       'source': source or _source_of(link),
                       'name': (name or (old or {}).get('name') or '')}] \
            + [x for x in d['links'] if x['link'] != link]
        d['links'] = d['links'][:limit]
    if query:
        d['queries'] = [query] + [q for q in d['queries'] if q != query]
        d['queries'] = d['queries'][:limit]
    _save(cfg, d)


def set_name(cfg, link: str, name: str) -> None:
    """Attach/update the display name of an already-recorded link."""
    if not link or not name:
        return
    d = _load(cfg)
    for x in d['links']:
        if x['link'] == str(link):
            if x.get('name') != str(name):
                x['name'] = str(name)
                _save(cfg, d)
            return


def name_of(cfg, link) -> Optional[str]:
    """The stored show name for a link (None when unknown)."""
    d = _load(cfg)
    e = next((x for x in d['links'] if x['link'] == str(link)), None)
    return (e or {}).get('name') or None


def last_link_for(cfg, title: str) -> Optional[str]:
    """The newest recorded link for a show name (resume from the shelf)."""
    t = (title or '').casefold().strip()
    if not t:
        return None
    for e in _load(cfg)['links']:            # newest first
        if (e.get('name') or '').casefold().strip() == t:
            return e['link']
    return None


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
    'title' is the stored show name when we know it (anime name instead of
    the raw link); the raw link stays in 'url'.
    """
    d = _load(cfg)
    out: List[dict] = []
    for e in d['links'][:limit]:
        src = e.get('source') or _source_of(e['link'])
        title = e.get('name') or e['link']
        out.append({'title': title, 'url': e['link'], 'source': src,
                    'kind': 'link', 'ts': e.get('ts') or 0})
    for q in d['queries'][:limit]:
        out.append({'title': q, 'url': None, 'source': 'recent search',
                    'kind': 'query', 'ts': 0})
    return out[:limit]
