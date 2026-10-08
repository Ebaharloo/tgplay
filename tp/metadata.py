"""tp.metadata - external metadata: AniList -> MAL id, Jikan -> episode titles."""
import difflib
import json
import os
import re
import subprocess
import time
from typing import Dict, List, Optional

from .http import HttpClient, _quiet_close

ANILIST = 'https://graphql.anilist.co'
_SEARCH = ('query($s:String){Page(page:1,perPage:8){media(search:$s,type:ANIME){'
           'idMal title{romaji english native} synonyms}}}')
_MISS = '?'
_GENERIC_EP = re.compile(r'^\s*episode\s*\d+\s*$', re.I)


def _read(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def _write(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(d, open(path, 'w'))


class Metadata:
    def __init__(self, config, http: Optional[HttpClient] = None, simkl=None,
                 cooldown: float = 1800.0):
        self.cfg = config
        self.http = http or HttpClient(timeout=20)
        self.cooldown = cooldown
        self._down = self._load_down()
        if simkl is None:
            from .simkl import Simkl
            simkl = Simkl(http=self.http)
        self.simkl = simkl

    # --- circuit breakers (a dead API must not be retried every run) --------
    @property
    def _down_file(self):
        return os.path.join(os.path.dirname(self.cfg.ep_titles), 'meta_down.json')

    def _load_down(self):
        try:
            return json.load(open(self._down_file))
        except Exception:
            return {}

    def _save_down(self):
        try:
            os.makedirs(os.path.dirname(self._down_file), exist_ok=True)
            json.dump(self._down, open(self._down_file, 'w'))
        except Exception:
            pass

    def down(self, source: str) -> bool:
        return time.time() < self._down.get(source, 0)

    def _mark_down(self, source: str):
        self._down[source] = time.time() + self.cooldown
        self._save_down()

    def _mark_up(self, source: str):
        if source in self._down:
            self._down.pop(source, None)
            self._save_down()

    def cached_mal(self, title: str):
        """MAL id from cache only - never blocks (for the menu)."""
        cache = _read(self.cfg.mal_ids, {})
        for k, v in cache.items():
            if k.casefold() == title.casefold():
                return v
        return None

    def _post(self, query, variables):
        req = self.http.request(ANILIST, method='POST',
                                headers={'Content-Type': 'application/json',
                                         'Accept': 'application/json'},
                                data=json.dumps(
                                    {'query': query, 'variables': variables}
                                ).encode())
        r = self.http.open(req)
        try:
            return json.load(r)
        finally:
            _quiet_close(r)

    def resolve_mal(self, title: str, ask: bool = True, prompt=None
                    ) -> Optional[int]:
        """Cached title -> MAL id (fuzzy match against AniList names)."""
        cache = _read(self.cfg.mal_ids, {})
        for k, v in cache.items():
            if k.casefold() == title.casefold():
                return v
        if self.down('anilist'):
            return None
        try:
            media = self._post(_SEARCH, {'s': title})['data']['Page']['media']
            self._mark_up('anilist')
        except Exception:
            self._mark_down('anilist')
            return None
        scored = []
        for m in media:
            if not m.get('idMal'):
                continue
            names = [v for v in m['title'].values() if v]
            names += [s for s in (m.get('synonyms') or []) if s]
            best = max(difflib.SequenceMatcher(
                None, title.casefold(), n.casefold()).ratio() for n in names)
            scored.append((best, m['idMal'], names))
        scored.sort(reverse=True)
        if not scored:
            return None
        top = scored[0]
        if top[0] >= 0.85 or (len(scored) == 1 and top[0] >= 0.6):
            cache[title] = top[1]
            _write(self.cfg.mal_ids, cache)
            return top[1]
        if ask and prompt:
            pick = prompt(scored)
            if pick is not None:
                cache[title] = pick
                _write(self.cfg.mal_ids, cache)
                return pick
        return None

    def ep_title(self, mal_id, ep, title: Optional[str] = None,
                 anilist_id=None) -> Optional[str]:
        """MAL/Jikan title first, then Simkl (which has many donghua titles)."""
        t = self._jikan_title(mal_id, ep)
        if t:
            return t
        # Simkl titles live under their own cache key so the two sources do not
        # shadow each other (Jikan often has *no* entry for donghua).
        key = f'simkl:{mal_id}' if mal_id else f'simkl:anilist:{anilist_id}'
        cache = _read(self.cfg.ep_titles, {})
        st = cache.get(key, {}).get(str(ep))
        if st:
            return st
        if self.simkl is not None and self.simkl.available() \
                and not self.down('simkl'):
            try:
                st = self.simkl.episode_title(ep, mal=mal_id, anilist=anilist_id,
                                              query=title)
                self._mark_up('simkl')
            except Exception:
                st = None
                self._mark_down('simkl')
            if st and not _GENERIC_EP.match(st):
                cache.setdefault(key, {})[str(ep)] = st
                _write(self.cfg.ep_titles, cache)
                return st
        return None

    def _jikan_title(self, mal_id, ep: int) -> Optional[str]:
        if self.down('jikan'):
            return None
        cache = _read(self.cfg.ep_titles, {})
        shows = cache.setdefault(str(mal_id), {})
        key = str(ep)
        if key in shows:
            t = shows[key]
            return None if t == _MISS else t
        if not shows:
            for n, t in self._fetch_titles(mal_id).items():
                shows[str(n)] = t
            shows.setdefault('_done', '1')
            _write(self.cfg.ep_titles, cache)
        t = shows.get(key)
        return None if not t or t == _MISS else t

    def _fetch_titles(self, mal_id: int) -> Dict[int, str]:
        """Short-timeout Jikan fetch; trips the breaker when it is unreachable."""
        titles: Dict[int, str] = {}
        page = 1
        while True:
            url = f'https://api.jikan.moe/v4/anime/{mal_id}/episodes?page={page}'
            d = None
            for attempt in range(2):
                r = subprocess.run(['curl', '-sS', '-m', '12', url],
                                   capture_output=True, text=True)
                try:
                    d = json.loads(r.stdout)
                    if d.get('data') is not None:
                        break
                except Exception:
                    d = None
                time.sleep(1.0 * (attempt + 1))
            if d is None:
                self._mark_down('jikan')
                return titles
            self._mark_up('jikan')
            for e in (d.get('data') or []):
                t = e.get('title') or ''
                if e.get('mal_id') and t and not t.startswith('Episode '):
                    titles[e['mal_id']] = t
            if not (d.get('pagination') or {}).get('has_next_page'):
                break
            page += 1
        return titles
