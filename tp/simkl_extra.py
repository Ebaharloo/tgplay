"""tp.simkl_extra - Simkl relations, episode air dates and the schedule feeds.

Titles are a bad key for "is this a new season": Simkl already knows the
relation graph. Two calls, both through `SimklAccount._api` (it refreshes the
token on a 401):

    GET /anime/{simkl_id}?extended=full   -> relations[]  (sequel/prequel/...)
    GET /anime/episodes/{simkl_id}        -> every episode with its air date

The schedule/discover feeds are CDN JSON (no auth), so the today/upcoming
panels work for a logged-out user too:

    GET data.simkl.in/calendar/anime.json                 -> today..+33 days
    GET data.simkl.in/discover/trending/anime/today_100.json
    GET /anime/airing is the same today slice as the calendar (not called)
    GET /search/random        (Bearer) -> the "surprise me" pick

Cached per simkl id: relations 7 days (relations rarely change), episodes
1 day (new episodes appear weekly). The whole feeds are cached in memory for
an hour. Failures never raise into the GUI: a failed fetch returns the stale
cache, else [].
"""
import json
import os
import threading
import time
import urllib.parse
from datetime import date, datetime

from .config import save_json
from .http import _quiet_close
from .simkl_account import SimklAccount

RELATIONS_TTL = 7 * 86400
EPISODES_TTL = 86400
FEED_TTL = 3600                 # the calendar/trending files change hourly
CDN = 'https://data.simkl.in'

_FEEDS: dict = {}               # name -> (stamp, rows), one process-wide cache


def _feed(name, fetch, ttl=FEED_TTL) -> list:
    """Cached whole-feed list; a failed fetch keeps the stale rows."""
    stamp, rows = _FEEDS.get(name) or (0, [])
    if rows and time.time() - stamp < ttl:
        return rows
    try:
        got = fetch()
    except Exception as ex:
        from . import log
        log.cprint(f'simkl: {name} feed failed ({ex})')
        return rows
    rows = [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []
    if rows:
        _FEEDS[name] = (time.time(), rows)
    return rows


def _day(s):
    """Local calendar date of one feed timestamp (None when unparsable)."""
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00')
                                      ).astimezone().date()
    except Exception:
        return None


def _item(it, kind) -> dict:
    """One feed row in the library's shape, so both panels render it as-is."""
    ids = it.get('ids') or {}
    ep = it.get('episode') or {}
    return {'title': str(it.get('title') or ''), 'simkl': ids.get('simkl_id'),
            'mal': ids.get('mal'), 'kind': kind, 'next_ep': ep.get('episode'),
            'air_date': it.get('date') or it.get('release_date')}

# one cache file is read-modify-written from several worker threads; without
# this lock the last writer wins and the other fetches are silently lost
_FILE_LOCK = threading.Lock()


class SimklExtra:
    def __init__(self, cfg, http=None, acc=None):
        self.cfg = cfg
        self.acc = acc or SimklAccount(cfg, http)

    def _cached(self, path, ttl, simkl_id, fetch):
        key = str(simkl_id or '')
        if not key:
            return []
        try:
            d = json.load(open(path))
            d = d if isinstance(d, dict) else {}
        except Exception:
            d = {}
        rec = d.get(key) or {}
        try:
            fresh = time.time() - float(rec.get('fetched') or 0) < ttl
        except (TypeError, ValueError):
            fresh = False
        if fresh and rec.get('data') is not None:
            return rec['data']
        try:
            data = fetch(simkl_id)
        except Exception as ex:
            from . import log
            log.cprint(f'simkl: {os.path.basename(path)} fetch failed ({ex})')
            data = None
        if data is None:                    # stale data beats nothing
            return rec.get('data')
        try:
            with _FILE_LOCK:                 # merge, do not clobber
                try:
                    d = json.load(open(path))
                    d = d if isinstance(d, dict) else {}
                except Exception:
                    d = {}
                d[key] = {'fetched': time.time(), 'data': data}
                save_json(path, d)
        except Exception as ex:
            from . import log
            log.cprint(f'simkl: {os.path.basename(path)} not saved ({ex})')
        return data

    def detail(self, simkl_id) -> dict:
        """Full /anime/{id} detail: relations, last_aired, total_episodes,
        status, first_aired, airs. Cached 7 days. {} when unavailable."""
        def fetch(sid):
            d = self.acc._api(f'/anime/{int(sid)}', {'extended': 'full'})
            if not isinstance(d, dict):
                return {}
            keep = ('relations', 'last_aired', 'first_aired',
                    'total_episodes', 'status', 'airs', 'title')
            return {k: d[k] for k in keep if k in d}
        got = self._cached(self.cfg.relations, RELATIONS_TTL, simkl_id, fetch)
        if isinstance(got, list):        # old cache shape: relations only
            return {'relations': got}
        return got or {}

    def relations(self, simkl_id) -> list:
        """[{title, year, poster, relation_type, is_direct, ids}] or []."""
        rel = self.detail(simkl_id).get('relations')
        return rel if isinstance(rel, list) else []

    def episodes(self, simkl_id) -> list:
        """[{episode, date, aired, title, runtime}] or []."""
        def fetch(sid):
            d = self.acc._api(f'/anime/episodes/{int(sid)}')
            if isinstance(d, list):
                return d
            eps = d.get('episodes') if isinstance(d, dict) else None
            return eps if isinstance(eps, list) else []
        got = self._cached(self.cfg.episodes, EPISODES_TTL, simkl_id, fetch)
        return got if isinstance(got, list) else []

    # --- schedule & discover (CDN JSON: no auth) --------------------------
    def _cdn(self, url) -> list:
        http = self.acc.http
        r = http.open(http.request(url, headers={'User-Agent': 'tgplay/1.0'}))
        try:
            return json.load(r)
        finally:
            _quiet_close(r)

    def _calendar(self) -> list:
        return self._cdn(f'{CDN}/calendar/anime.json?' + urllib.parse.urlencode(
            {'client_id': self.acc.client_id or '', 'app-name': 'tgplay',
             'app-version': '1.0'}))

    def calendar(self, days: int = 0) -> list:
        """Every anime episode airing from today to `days` ahead, soonest
        first. `days=0` is today (what /anime/airing returns)."""
        today = date.today()
        out = []
        for r in _feed('calendar', self._calendar):
            when = _day(r.get('date'))
            if when is None or when < today or (when - today).days > days:
                continue
            out.append(_item(r, 'today' if when == today else 'upcoming'))
        out.sort(key=lambda x: str(x.get('air_date')))
        return out

    def trending(self) -> list:
        """Simkl's most-watched-today anime (100 rows, no auth)."""
        url = (f'{CDN}/discover/trending/anime/today_100.json?'
               + urllib.parse.urlencode(
                   {'client_id': self.acc.client_id or '', 'app-name': 'tgplay',
                    'app-version': '1.0'}))
        return [_item(r, 'trending') for r in _feed('trending',
                                                    lambda: self._cdn(url))]

    def random(self) -> dict:
        """One random anime: {'simkl', 'title'}. The title is the URL slug -
        one call, and a slug is searchable on our sources."""
        d = self.acc._api('/search/random')
        if not isinstance(d, dict) or not d.get('simkl_id'):
            return {}
        slug = str(d.get('simkl_url') or '').rstrip('/').rsplit('/', 1)[-1]
        return {'simkl': d['simkl_id'], 'title': slug.replace('-', ' ')}
