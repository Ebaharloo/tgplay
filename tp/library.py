"""tp.library - the watch list (Simkl-backed) + "play from the list".

`entries()` reads the user's Simkl library (watching + plan-to-watch) and
normalises it; `up_next()` keeps the shows with a next unwatched episode;
`find_source()` resolves a list title to one of our sources (axp dub / agp sub)
so the app can jump straight into the player.
"""
import difflib
import json
import urllib.parse
from typing import List, Optional, Tuple

from .http import HttpClient, _quiet_close
from .simkl_account import SimklAccount

CAL = 'https://data.simkl.in/calendar/v2/anime.json'


def entries(cfg, http: Optional[HttpClient] = None,
            statuses=('watching', 'plantowatch')) -> List[dict]:
    try:
        return SimklAccount(cfg, http).library(statuses)
    except Exception:
        return []


def up_next(cfg, http: Optional[HttpClient] = None) -> List[dict]:
    try:
        return SimklAccount(cfg, http).up_next()
    except Exception:
        return []


def _all(cfg, http=None) -> List[dict]:
    try:
        return SimklAccount(cfg, http).library(
            ('watching', 'plantowatch', 'hold', 'completed', 'dropped'))
    except Exception:
        return []


def calendar(cfg, http: Optional[HttpClient] = None, days: int = 21,
             limit: int = 40) -> List[dict]:
    """Upcoming episodes **for the user's own shows**, from Simkl's public
    calendar (`data.simkl.in`, no auth). This is the real 'what airs next'."""
    from datetime import datetime, timedelta, timezone
    acc = SimklAccount(cfg, http)
    try:
        ids = {e['simkl'] for e in acc.library(('watching', 'plantowatch'))
               if e.get('simkl')}
    except Exception:
        ids = set()
    if not ids:
        return []
    http = http or HttpClient()
    url = CAL + '?' + urllib.parse.urlencode(
        {'client_id': acc.client_id or '', 'app-name': 'tgplay',
         'app-version': '1.0'})
    try:
        r = http.open(http.request(url, headers={'User-Agent': 'tgplay/1.0'}))
        try:
            d = json.load(r)
        finally:
            _quiet_close(r)
    except Exception:
        return []
    meta = d.get('metadata') or {}
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days)
    out = []
    for e in d.get('calendar') or []:
        if e.get('simkl_id') not in ids:
            continue
        try:
            dt = datetime.fromisoformat(str(e.get('date')).replace('Z', '+00:00'))
        except Exception:
            continue
        if not (now <= dt <= horizon):
            continue
        ep = e.get('episode') or {}
        m = meta.get(str(e.get('simkl_id'))) or {}
        out.append({'title': m.get('title') or '', 'simkl': e.get('simkl_id'),
                    'air_date': e.get('date'), 'next_ep': ep.get('episode'),
                    'ep_title': ep.get('title'), 'kind': 'upcoming'})
    out.sort(key=lambda x: str(x.get('air_date')))
    return out[:limit]


def recently_aired(cfg, http: Optional[HttpClient] = None, days: int = 7,
                   limit: int = 40) -> List[dict]:
    """Episodes of your shows that aired in the **last `days`** (new to watch)."""
    from datetime import date, timedelta
    rows = _all(cfg, http)
    today = date.today()
    cut = (today - timedelta(days=days)).isoformat()
    out = []
    for e in rows:
        d = str(e.get('air_date') or '')[:10]
        if d and cut <= d < today.isoformat():
            e['kind'] = 'aired'
            out.append(e)
    out.sort(key=lambda e: str(e['air_date']), reverse=True)
    return out[:limit]


def remaining(cfg, http: Optional[HttpClient] = None, limit: int = 80) -> List[dict]:
    """The 'continue watching' backlog: every started show that still has a
    next unwatched episode (however old), most recent first."""
    out = []
    for e in up_next(cfg, http):
        e['kind'] = 'remaining'
        out.append(e)
    out.sort(key=lambda e: str(e.get('air_date') or ''), reverse=True)
    return out[:limit]


def recent(cfg, http: Optional[HttpClient] = None, limit: int = 15) -> List[dict]:
    """What you watched most recently (the history rail)."""
    rows = [e for e in _all(cfg, http) if e.get('last_watched')]
    rows.sort(key=lambda e: str(e['last_watched']), reverse=True)
    return rows[:limit]


def find_source(title: str, http: Optional[HttpClient] = None
                ) -> Optional[Tuple[str, str]]:
    """Best match for `title` on our sources -> (source_id, target).

    Prefers the closest title match; ties go to AnimeX (English dub).
    """
    if not title:
        return None
    try:
        from .search import search_all
        results = search_all(title, http=http, sources=('agp', 'axp'))
    except Exception:
        return None
    if not results:
        return None
    want = title.casefold().strip()

    def score(r):
        got = str(r.get('title', '')).casefold().strip()
        return (difflib.SequenceMatcher(None, want, got).ratio(),
                1 if r.get('source') == 'axp' else 0)

    best = max(results, key=score)
    return (best.get('source') or 'agp', best.get('url'))
