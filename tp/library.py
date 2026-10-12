"""tp.library - the watch list (Simkl-backed): calendar, backlog, history.

`overview()` does **one** library fetch + **one** calendar fetch and derives:
  cal  = 📅 upcoming episodes (next `cal_days`) + ✅ aired in the last `aired_days`
  rem  = every started show with a next unwatched episode (continue watching)
  hist = recently watched
`find_source()` resolves a list title to one of our sources (axp dub / agp sub).
"""
import difflib
import json
import urllib.parse
from typing import List, Optional, Tuple

from .http import HttpClient, _quiet_close
from .simkl_account import SimklAccount

CAL = 'https://data.simkl.in/calendar/v2/anime.json'


def _fetch_calendar(http, client_id: Optional[str], ids: set, days: int) -> List[dict]:
    """Upcoming episodes (next `days`) for the given Simkl ids, soonest first."""
    from datetime import datetime, timedelta, timezone
    if not ids:
        return []
    url = CAL + '?' + urllib.parse.urlencode(
        {'client_id': client_id or '', 'app-name': 'tgplay',
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
    return out


def overview(cfg, http: Optional[HttpClient] = None, aired_days: int = 7,
             cal_days: int = 14, hist_limit: int = 15) -> dict:
    """Fetch the library once (+ the calendar once) and derive everything."""
    from datetime import date, timedelta
    acc = SimklAccount(cfg, http)
    http = http or HttpClient()
    rows = acc.library(('watching', 'plantowatch', 'hold', 'completed', 'dropped'))
    watch_ids = {e['simkl'] for e in rows
                 if e.get('status') in ('watching', 'plantowatch') and e.get('simkl')}
    today = date.today()
    cut = (today - timedelta(days=aired_days)).isoformat()
    upcoming = _fetch_calendar(http, acc.client_id, watch_ids, cal_days)
    aired = []
    for e in rows:
        d = str(e.get('air_date') or '')[:10]
        if d and cut <= d < today.isoformat():
            e['kind'] = 'aired'
            aired.append(e)
    aired.sort(key=lambda e: str(e['air_date']), reverse=True)
    rem = [dict(e, kind='remaining') for e in rows
           if e.get('status') == 'watching' and e.get('next_ep') and e.get('title')]
    rem.sort(key=lambda e: str(e.get('air_date') or ''), reverse=True)
    hist = [e for e in rows if e.get('last_watched')]
    hist.sort(key=lambda e: str(e['last_watched']), reverse=True)
    return {'cal': upcoming + aired, 'rem': rem, 'hist': hist[:hist_limit]}


def _norm_title(t) -> str:
    """Collapse newlines/wrapping (feed titles show on '2 lines' sometimes)
    so a copy-pasted multi-line title still matches a search result."""
    return ' '.join(str(t or '').split()).casefold().strip()


_YEAR = None


def title_variants(title: str) -> List[str]:
    """Search variants for a title, widest last.

    The Simkl/library name is not what our sites use: a show can live on
    AnimeGate as 'Fanren Xiu Xian Zhuan: Xinghai Feichi Prologue' while Simkl
    says 'A Record of Mortal's Journey to Immortality (2024)'. We search the
    full name first, then the base name (without the season/movie qualifier)
    so the site's own naming shows up in the results.
    """
    import re
    t = ' '.join(str(title or '').split())
    if not t:
        return []
    out = [t]
    t2 = re.sub(r'\s*\(\d{4}\)\s*$', '', t).strip()          # '(2024)' year
    if t2 and t2 != t:
        out.append(t2)
    # strip the part after ':' or ' - ' (season/movie subtitles), then bare
    t3 = re.split(r'\s*[:–—-]\s{1,}', t2)[0].strip() if ':' in t2 or ' – ' in t2 else t2
    base = re.sub(
        r'\s+(\d+(?:st|nd|rd|th)?\s+(?:season|part)|season\s+\d+|part\s+\d+'
        r'|movies?|ova(?:\s*s?)|specials?|prologue|recap|volume\s+\d+)$',
        '', t2, flags=re.I).strip()
    if base and base != t2 and base not in out:
        out.append(base)
    if t3 and t3 not in out and t3 != base:
        out.append(t3)
    return out


def search_variants(title: str, http: Optional[HttpClient] = None,
                    limit_each: int = 12) -> List[dict]:
    """Results for all title_variants merged + de-duplicated, best first.

    Stops widening (base-name search) as soon as an exact-name hit exists,
    so the common case stays one network search like before.
    """
    out: List[dict] = []
    seen = set()
    for q in title_variants(title):
        try:
            from .search import search_all
            got = search_all(q, http=http, sources=('agp', 'axp'),
                             limit=limit_each) or []
        except Exception:
            got = []
        for r in got:
            u = r.get('url')
            if u and u not in seen:
                seen.add(u)
                out.append(r)
        if _norm_has_exact(out, title) or len(out) >= limit_each:
            break                       # confident enough, no wider search
    return ranked(out, title)


def _norm_has_exact(results, title) -> bool:
    want = _norm_title(title)
    return any(_norm_title(r.get('title', '')) == want for r in results)


def ranked(results: List[dict], title: str) -> List[dict]:
    """Search results ordered best-match first (so the GUI list starts with
    the closest title). Ties go to AnimeX (English dub)."""
    want = _norm_title(title)

    def score(r):
        got = _norm_title(r.get('title', ''))
        return (difflib.SequenceMatcher(None, want, got).ratio(),
                1 if r.get('source') == 'axp' else 0)

    return sorted(results, key=score, reverse=True)


def find_source(title: str, http: Optional[HttpClient] = None
                ) -> Optional[Tuple[str, str]]:
    """Best match for `title` on our sources -> (source_id, target)."""
    if not title:
        return None
    got = search_variants(title, http=http)
    if not got:
        return None
    best = got[0]
    return (best.get('source') or 'agp', best.get('url'))
