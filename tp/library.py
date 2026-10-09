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
