"""tp.library - the watch list (Simkl-backed) + "play from the list".

`entries()` reads the user's Simkl library (watching + plan-to-watch) and
normalises it; `up_next()` keeps the shows with a next unwatched episode;
`find_source()` resolves a list title to one of our sources (axp dub / agp sub)
so the app can jump straight into the player.
"""
import difflib
from typing import List, Optional, Tuple

from .http import HttpClient
from .simkl_account import SimklAccount


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


def feed(cfg, http: Optional[HttpClient] = None, limit: int = 25) -> List[dict]:
    """The sidebar feed: dated upcoming episodes (soonest first), then the
    shows with a next episode but no air date (the old 'library/up next')."""
    rows = _all(cfg, http)
    dated = [e for e in rows if e.get('air_date')]
    dated.sort(key=lambda e: str(e['air_date']))
    undated = [e for e in rows
               if not e.get('air_date') and e.get('next_ep')
               and e.get('status') == 'watching']
    return (dated + undated)[:limit]


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
