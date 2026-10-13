"""tp.metadata - external metadata.

Primary source is **MyAnimeList directly** (the Jikan API is often down, and MAL
itself knows donghua titles like 'Mushen Ji' that AniList spells differently):

    title  -> MAL id       : myanimelist.net/search/prefix.json  (fuzzy)
    MAL id -> episode names: myanimelist.net/anime/{id}/episode (scraped)

Fallbacks: AniList (title -> MAL id), Simkl (episode names). Each source has a
circuit breaker so a dead API is skipped for a while.
"""
import difflib
import html as _html
import json
import os
import re
import subprocess
import time
import urllib.parse
from typing import Dict, Optional

from .http import HttpClient, _quiet_close
from .bangumi import Bangumi, cjk_title as _cjk
from .translate import Translator
from .titles import clean_ep_name

ANILIST = 'https://graphql.anilist.co'
_SEARCH = ('query($s:String){Page(page:1,perPage:8){media(search:$s,type:ANIME){'
           'idMal episodes title{romaji english native} synonyms}}}')
_GENERIC_EP = re.compile(
    r'^\s*(episode\s*\d+|ep\s*\d+|第?\s*\d+\s*[集话話話])[\s.:。-]*$', re.I)
_MAL_SEARCH = 'https://myanimelist.net/search/prefix.json'
_MAL_UA = 'Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/130.0'


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
                 cooldown: float = 900.0):
        self.cfg = config
        self.http = http or HttpClient(timeout=20)
        # how long a failed source is skipped before we try it again each run
        self.cooldown = float(os.environ.get(
            'AGP_META_COOLDOWN', cooldown))
        self._down = self._load_down()
        self._refreshed = set()  # mal ids already refreshed this run
        if simkl is None:
            from .simkl import Simkl
            simkl = Simkl(http=self.http)
        self.simkl = simkl
        self.bangumi = Bangumi()
        self._bgm_done = set()
        self.translator = Translator(config.translations, self.http)

    # --- circuit breakers --------------------------------------------------
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
        """MAL id from cache only - never blocks."""
        cache = _read(self.cfg.mal_ids, {})
        for k, v in cache.items():
            if k.casefold() == title.casefold():
                return v
        return None

    # --- MAL slug cache (episode URLs need /anime/<id>/<slug>/episode) -----
    @property
    def _slugs_file(self):
        return os.path.join(os.path.dirname(self.cfg.mal_ids), 'mal_slugs.json')

    def _slug_get(self, mal_id):
        return _read(self._slugs_file, {}).get(str(mal_id))

    def _slug_put(self, mal_id, slug):
        d = _read(self._slugs_file, {})
        d[str(mal_id)] = slug
        _write(self._slugs_file, d)

    def _mal_slug(self, mal_id) -> Optional[str]:
        s = self._slug_get(mal_id)
        if s:
            return s
        try:
            doc = self._curl(f'https://myanimelist.net/anime/{mal_id}')
            m = re.search(
                r'<link rel="canonical" href="https://myanimelist\.net/anime/'
                r'\d+/([^"/]+)"', doc)
            if m:
                self._slug_put(mal_id, m.group(1))
                return m.group(1)
        except Exception:
            pass
        return None

    def _remember(self, title: str, mal_id: int, slug: Optional[str] = None):
        cache = _read(self.cfg.mal_ids, {})
        cache[title] = mal_id
        _write(self.cfg.mal_ids, cache)
        if slug:
            self._slug_put(mal_id, slug)

    @staticmethod
    def _curl(url: str, timeout: int = 15) -> str:
        r = subprocess.run(['curl', '-sS', '-m', str(timeout), '-A', _MAL_UA,
                            url], capture_output=True, text=True)
        if not r.stdout:
            raise OSError('empty response')
        return r.stdout

    # --- title -> MAL id ---------------------------------------------------
    def _mal_search(self, title: str):
        """(MAL id, slug) for a title, or (None, None)."""
        url = _MAL_SEARCH + '?' + urllib.parse.urlencode(
            {'type': 'anime', 'keyword': title})
        d = json.loads(self._curl(url))
        items = []
        for c in d.get('categories', []):
            for it in (c.get('items') or []):
                if it.get('id') and it.get('name'):
                    m = re.search(r'/anime/\d+/([^"/]+)', it.get('url') or '')
                    items.append((it['name'], it['id'],
                                  m.group(1) if m else None))
        if not items:
            return None, None
        scored = sorted(
            ((difflib.SequenceMatcher(None, title.casefold(), n.casefold())
              .ratio(), i, s) for n, i, s in items), reverse=True)
        best, mid, slug = scored[0]
        return (mid, slug) if best >= 0.6 else (None, None)

    def resolve_mal(self, title: str, ask: bool = True, prompt=None
                    ) -> Optional[int]:
        """Fuzzy title -> MAL id (MAL search first, AniList scored fallback).

        The result is pinned to the link by the caller (`remember_link_mal`),
        so the same page always keeps the same id."""
        cache = _read(self.cfg.mal_ids, {})
        for k, v in cache.items():
            if k.casefold() == title.casefold():
                return v
        # AniList scored candidates (also used by callers with a prompt)
        scored = []
        if not self.down('anilist'):
            try:
                media = self._post(_SEARCH,
                                   {'s': title})['data']['Page']['media']
                self._mark_up('anilist')
                for m in media or []:
                    if not m.get('idMal'):
                        continue
                    names = [v for v in m['title'].values() if v]
                    names += [s for s in (m.get('synonyms') or []) if s]
                    best = max((difflib.SequenceMatcher(
                        None, title.casefold(), n.casefold()).ratio()
                        for n in names), default=0.0)
                    scored.append((best, m['idMal'], names))
            except Exception:
                self._mark_down('anilist')
        # MAL (primary)
        if not self.down('mal'):
            try:
                mid, slug = self._mal_search(title)
                self._mark_up('mal')
                if mid:
                    self._remember(title, mid, slug)
                    return mid
            except Exception:
                self._mark_down('mal')
        if not scored:
            return None
        scored.sort(reverse=True)
        top = scored[0]
        if top[0] >= 0.85 or (len(scored) == 1 and top[0] >= 0.6):
            self._remember(title, top[1])
            return top[1]
        if ask and prompt:
            pick = prompt(scored)
            if pick is not None:
                self._remember(title, pick)
                return pick
        return None

    # --- per-link id pinning (an id found once sticks to the page) ------
    def link_mal(self, link: str) -> Optional[int]:
        return _read(self.cfg.mal_ids, {}).get(f'link:{str(link)}')

    def remember_link_mal(self, link: str, mal_id) -> None:
        cache = _read(self.cfg.mal_ids, {})
        key = f'link:{str(link)}'
        if cache.get(key) != mal_id:
            cache[key] = mal_id
            _write(self.cfg.mal_ids, cache)

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

    # --- episode titles ----------------------------------------------------
    def ep_title(self, mal_id, ep, title: Optional[str] = None,
                 anilist_id=None) -> Optional[str]:
        """MAL episode name first, then Bangumi (Chinese), then Simkl."""
        if mal_id and not self.down('mal'):
            try:
                t = clean_ep_name(self._mal_title(mal_id, ep, title))
                self._mark_up('mal')
                if t and not _GENERIC_EP.match(t):
                    return t
            except Exception:
                self._mark_down('mal')
        if mal_id:
            bt = clean_ep_name(self.bangumi_titles(mal_id, title).get(str(ep)))
            if bt and not _GENERIC_EP.match(bt):
                return bt
        key = f'simkl:{mal_id}' if mal_id else f'simkl:anilist:{anilist_id}'
        cache = _read(self.cfg.ep_titles, {})
        st = clean_ep_name(cache.get(key, {}).get(str(ep)))
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
            st = clean_ep_name(st)
            if st and not _GENERIC_EP.match(st):
                cache.setdefault(key, {})[str(ep)] = st
                _write(self.cfg.ep_titles, cache)
                return st
        return None

    def _cjk_title(self, mal_id, title):
        try:
            info = self.simkl.info(mal=mal_id) if mal_id else None
        except Exception:
            info = None
        return _cjk(info, title or '')

    def bangumi_titles(self, mal_id, title) -> Dict[str, str]:
        """Merge Bangumi Chinese episode names (once per run)."""
        cur = _read(self.cfg.ep_titles, {}).get(str(mal_id)) or {}
        if not mal_id or self.down('bangumi') or mal_id in self._bgm_done:
            return cur
        self._bgm_done.add(mal_id)
        kw = self._cjk_title(mal_id, title)
        if not kw:
            return cur
        try:
            eps = self.bangumi.grouped_episodes(kw)  # all seasons, offset
            self._mark_up('bangumi')
        except Exception:
            self._mark_down('bangumi')
            return cur
        if not eps:
            return cur
        cache = _read(self.cfg.ep_titles, {})
        shows = cache.get(str(mal_id)) or {}
        before = len(shows)
        for n, t in eps.items():
            t = clean_ep_name(t)
            if t and not _GENERIC_EP.match(t):
                shows.setdefault(str(n), t)
        if len(shows) != before:
            shows.setdefault('_done', '1')
            cache[str(mal_id)] = shows
            _write(self.cfg.ep_titles, cache)
        self.translator.ensure(list(eps.values()))  # zh -> en (cached)
        return shows

    def _mal_title(self, mal_id, ep: int,
                   title: Optional[str] = None) -> Optional[str]:
        cache = _read(self.cfg.ep_titles, {})
        shows = cache.get(str(mal_id)) or {}
        key = str(ep)
        if key in shows:
            return shows[key]
        # unknown episode -> refresh the series ONCE this run (picks up new,
        # still-airing episodes; never overwrites/costs on known ones)
        if mal_id not in self._refreshed:
            self._refreshed.add(mal_id)
            self.refresh_titles(mal_id, title)
            shows = _read(self.cfg.ep_titles, {}).get(str(mal_id)) or {}
        return shows.get(key)

    def refresh_titles(self, mal_id, title=None) -> None:
        """Scrape MAL (and Bangumi) and MERGE - existing episode names are
        never overwritten, so we fetch each once and keep it forever."""
        if not mal_id:
            return
        if not self.down('mal'):
            try:
                fetched = self._mal_titles(mal_id)
                self._mark_up('mal')
                self._merge(mal_id, fetched)
            except Exception:
                self._mark_down('mal')
        self.bangumi_titles(mal_id, title)
        self.simkl_titles(mal_id, title)

    def simkl_titles(self, mal_id, title=None) -> Dict[int, str]:
        """Simkl episode names (the third named source): resolve the show via
        its MAL id, merge non-generic titles under 'simkl:{mal_id}' — the
        exact key `TitleService.labels()` reads. Missing names only; older
        cached names are never overwritten."""
        if self.simkl is None or not mal_id:
            return {}
        if not self.simkl.available() or self.down('simkl'):
            return {}
        try:
            sid = self.simkl.resolve(mal=mal_id)
            if not sid:
                return {}
            eps = self.simkl.episodes(sid) or {}
        except Exception:
            self._mark_down('simkl')
            return {}
        cache = _read(self.cfg.ep_titles, {})
        shows = cache.get(f'simkl:{mal_id}') or {}
        before = len(shows)
        for n, t in list(eps.items()):
            t = clean_ep_name(t)
            if t and not _GENERIC_EP.match(t):
                shows.setdefault(str(n), t)
        if len(shows) != before:
            cache[f'simkl:{mal_id}'] = shows
            _write(self.cfg.ep_titles, cache)
        return eps

    def _merge(self, mal_id, titles: Dict[int, str]) -> None:
        if not titles:
            return
        cache = _read(self.cfg.ep_titles, {})
        shows = cache.get(str(mal_id)) or {}
        before = len(shows)
        for n, t in titles.items():
            t = clean_ep_name(t)
            if t and not _GENERIC_EP.match(t):
                shows.setdefault(str(n), t)   # keep the first name we saw
        if len(shows) != before:
            shows.setdefault('_done', '1')
            cache[str(mal_id)] = shows
            _write(self.cfg.ep_titles, cache)

    def _mal_titles(self, mal_id: int) -> Dict[int, str]:
        """Scrape MAL's episode list (raises when MAL is unreachable)."""
        base = f'https://myanimelist.net/anime/{mal_id}'
        slug = self._mal_slug(mal_id)
        if slug:
            base += f'/{slug}'
        titles: Dict[int, str] = {}
        page = 1
        while True:
            doc = self._curl(f'{base}/episode?page={page}')
            if 'episode-number' not in doc:
                break
            for row in doc.split('<tr'):
                mn = re.search(r'episode-number[^>]*>\s*([\d.]+)\s*<', row)
                if not mn:
                    continue
                mt = re.search(r'episode-title[^>]*>\s*(?:<a[^>]*>)?([^<]+)',
                               row)
                t = _html.unescape(mt.group(1)).strip() if mt else ''
                if t and not _GENERIC_EP.match(t):
                    try:
                        titles[int(float(mn.group(1)))] = t
                    except ValueError:
                        pass
            if f'page={page + 1}' not in doc:
                break
            page += 1
        return titles
