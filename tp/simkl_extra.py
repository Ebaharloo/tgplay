"""tp.simkl_extra - Simkl relations + episode air dates, cached.

Titles are a bad key for "is this a new season": Simkl already knows the
relation graph. Two calls, both through `SimklAccount._api` (it refreshes the
token on a 401):

    GET /anime/{simkl_id}?extended=full   -> relations[]  (sequel/prequel/...)
    GET /anime/episodes/{simkl_id}        -> every episode with its air date

Cached per simkl id: relations 7 days (relations rarely change), episodes
1 day (new episodes appear weekly). Failures never raise into the GUI: a
failed fetch returns the stale cache, else [].
"""
import json
import os
import threading
import time

from .config import save_json
from .simkl_account import SimklAccount

RELATIONS_TTL = 7 * 86400
EPISODES_TTL = 86400

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
