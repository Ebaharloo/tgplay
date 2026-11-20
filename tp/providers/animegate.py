"""tp.providers.animegate - animegate.ir catalog + signed-CDN byte sources.

Ported from the original `agp`, with the HTTP plumbing delegated to
`tp.http.HttpClient` and the byte source to `tp.sources.HttpSource`.
"""
import glob
import json
import os
import re
import sqlite3
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from ..http import HttpClient, _quiet_close
from ..sources import HttpSource
from ..features.audio import NoAudio
from ..features.auth import AgpAuth
from ..features.quality import AgpQuality
from ..features.servers import AgpServers
from ..features.sizes import AgpSizes
from ..features.titles import MalTitles
from ..features.warm import MirrorWarm
from .base import NoServersYet, Provider

BASE = 'https://animegate.ir'


# --- site helpers -----------------------------------------------------------
def firefox_cookies() -> Dict[str, str]:
    dbs = glob.glob(os.path.expanduser(
        '~/.mozilla/firefox/*.default-release/cookies.sqlite'))
    if not dbs:
        raise RuntimeError('no firefox cookies db (log in to animegate in Firefox)')
    con = sqlite3.connect(f'file:{dbs[0]}?immutable=1', uri=True)
    try:
        return dict(con.execute(
            "SELECT name, value FROM moz_cookies WHERE host='animegate.ir'"))
    finally:
        con.close()


def hdrs(cookies: Dict[str, str], extra: Optional[Dict[str, str]] = None):
    h = {'User-Agent': 'Mozilla/5.0 Gecko/20100101 Firefox/130.0',
         'Cookie': '; '.join(
             f'{n}={urllib.parse.unquote(urllib.parse.quote(v))}'
             for n, v in (cookies or {}).items())}
    if extra:
        h.update(extra)
    return h


def parse_page(page: str) -> Tuple[List[dict], str, Optional[str]]:
    """(groups, csrf, anime_id) from the anime page HTML."""
    i = page.find(":links='")
    if i < 0:
        raise ValueError('no links (logged out / cookie expired?)')
    groups, _ = json.JSONDecoder().raw_decode(page[i + 8:])
    groups = [g for g in groups if g.get('data') and isinstance(g['data'], list)]
    m = re.search(r':anime_id="(\d+)"', page) or re.search(r'anime-id="(\d+)"', page)
    csrf = re.search(r'csrf-token" content="([^"]+)"', page)
    if csrf is None:
        raise ValueError('no csrf token (page changed / not logged in)')
    return groups, csrf.group(1), (m.group(1) if m else None)


def slug_title(url: str) -> str:
    slug = re.search(r'/anime/([^/?#]+)', url).group(1)
    words = re.sub(r'\d+.*$', '', slug).replace('-', ' ').strip()
    return ' '.join(w.capitalize() if w.islower() else w for w in words.split())


def pick_group(groups: List[dict], quality: Optional[str] = None,
               all_groups: bool = False, prompt=None) -> dict:
    if not groups:
        raise ValueError('nothing playable on this page (links not '
                         'uploaded yet on the site)')
    if quality:
        gs = [g for g in groups if quality.lower() in str(g['label']).lower()]
        if not gs:
            raise ValueError(f'no quality matching "{quality}"')
        return gs[0]
    if len(groups) > 1 and not all_groups and prompt is not None:
        return prompt(groups)
    return groups[0]


def fetch_page(url, cookies, http):
    r = http.open(http.request(url, headers=hdrs(cookies)))
    try:
        return r.read().decode('utf-8', 'replace')
    finally:
        _quiet_close(r)


def get_base(url, cookies, http):
    groups, csrf, aid = parse_page(fetch_page(url, cookies, http))
    return groups, csrf, aid


def fetch_eps_window(aid, gid, start, end, csrf, cookies, http) -> List[dict]:
    u = (f'{BASE}/anime/download-links/{aid}'
         f'?index={gid}&start={start}&end={end}&page=1')
    extra = {'Accept': 'application/json',
             'X-Requested-With': 'XMLHttpRequest',
             'X-CSRF-TOKEN': csrf,
             'X-XSRF-TOKEN': urllib.parse.unquote(cookies.get('XSRF-TOKEN', ''))}
    r = http.open(http.request(u, headers=hdrs(cookies, extra)))
    try:
        d = json.loads(r.read().decode())
    finally:
        _quiet_close(r)
    return d.get('data') if d.get('status') else []


def all_eps(aid, gid, group, csrf, cookies, http) -> Dict[int, str]:
    eps = {e['es']: e['link'] for e in group['data']}
    if aid and eps:
        hi = max(eps)
        windows = [(lo, min(lo + 51, hi)) for lo in range(1, hi + 1, 52)
                   if any(k not in eps for k in range(lo, min(lo + 51, hi) + 1))]
        with ThreadPoolExecutor(6) as ex:
            for got in ex.map(
                    lambda w: fetch_eps_window(aid, gid, w[0], w[1], csrf,
                                               cookies, http), windows):
                for e in got:
                    eps[e['es']] = e['link']
    return eps


# --- provider ---------------------------------------------------------------
class GateAuth:
    """AnimeGate session health (OO): is the Firefox cookie login alive?

    `alive()` fetches the site home with the current browser cookies and
    reports whether the session still passes ('logged out' / cookie expired
    detection, matching the errors `parse_page` raises on real loads).
    `open_login()` opens the login page in the user's browser.
    While auth is down, callers keep working with the data they have
    (results list, history, last session) - nothing is wiped."""

    LOGIN_URL = BASE + '/login'

    def __init__(self, http=None, cookies: Dict[str, str] = None):
        self.http = http or HttpClient()
        self._cookies = cookies
        self._page: Optional[str] = None

    def cookies(self) -> Dict[str, str]:
        # Re-read whenever the jar is empty: the app can start before the user
        # logs in (or a read can fail), and a cached empty jar made every
        # retry "logged out" forever even after a successful login.
        if not self._cookies:
            try:
                self._cookies = firefox_cookies()
            except Exception:
                self._cookies = {}
        return self._cookies

    def alive(self) -> Tuple[bool, str]:
        """(session-ok, reason) for the current cookie login."""
        cks = self.cookies()
        if not cks:
            return False, ('no AnimeGate cookies - log in to animegate '
                           'in Firefox, then retry')
        try:
            page = self._page = fetch_page(BASE, cks, self.http)
        except Exception as ex:
            return False, f'AnimeGate unreachable ({type(ex).__name__}: {ex})'
        if re.search(r'logout', page, re.I):
            return True, 'ok'
        if re.search(r'href="[^"]*/login"', page, re.I):
            return False, 'AnimeGate session is logged out - open the login page'
        return True, 'site up (login state unknown)'

    def open_login(self) -> None:
        import webbrowser
        webbrowser.open(self.LOGIN_URL)

    def session_cookie(self) -> Optional[str]:
        """The live session cookie name/value (None after logout/expiry)."""
        return self.cookies().get('animegate_mr_session')


class AnimeGateProvider(Provider):
    audio = NoAudio()          # one audio track per file (features.audio)
    quality = AgpQuality()
    servers = AgpServers()
    sizes = AgpSizes()
    titles = MalTitles()
    warm = MirrorWarm()
    auth = AgpAuth()

    def __init__(self, url, quality=None, all_groups=False, http=None,
                 cookies=None, prompt=None):
        self.url = url
        self.quality_name = quality
        self.all_groups = all_groups
        self.http = http or HttpClient()
        self._cookies = cookies
        self.prompt = prompt
        # a direct /download/ link has no /anime/ slug: it IS one episode.
        # slug_title() would crash on it ('links are not belong to AGP').
        self.single = '/download/' in url
        if self.single:
            from urllib.parse import unquote
            name = unquote(url.rstrip('/').rsplit('/', 1)[-1])
            self.title = re.sub(r'^\[[^\]]+\]\s*', '', name)
            self._loaded = True
            self._eps = {1: url}
            self._labels = {1: self.title}
            self._cs = self._cookies if self._cookies is not None \
                else firefox_cookies()
            self.group = None
            return
        self.title = slug_title(url)
        self.group = None
        self.groups = None
        self._loaded = False
        self._sizes: Dict[int, int] = {}
        self._eps: Dict[int, str] = {}
        self._aid = self._gid = self._csrf = None
        self._cs: Dict[str, str] = {}
        self._labels: Dict[int, str] = {}

    def fetch_groups(self) -> List[dict]:
        cs = self._cookies if self._cookies is not None else firefox_cookies()
        groups, csrf, aid = get_base(self.url, cs, self.http)
        for g in groups:  # keep the site's labels for nicer menus
            for e in g.get('data', []):
                self._labels.setdefault(e.get('es'), e.get('label'))
        self._cs, self._csrf, self._aid, self.groups = cs, csrf, aid, groups
        return groups

    def select(self, quality=None):
        if self.groups is None:
            self.fetch_groups()
        want = quality if quality is not None else self.quality_name
        if not self.groups:
            raise NoServersYet(
                f'"{self.title}": nothing playable uploaded on AnimeGate '
                'yet (the page exists but has no links) — pick a season '
                'part or another source below')
        try:
            self.group = pick_group(self.groups, want, self.all_groups,
                                    self.prompt)
        except ValueError:
            self.group = self.groups[0]
            try:
                from .. import log
                log.cprint(f'quality "{want}" not found - using '
                           f'"{self.group.get("label")}"')
            except Exception:
                pass
        self._gid = self.group['id']
        self._eps = all_eps(self._aid, self.group['id'], self.group,
                            self._csrf, self._cs, self.http)
        self._loaded = True
        return self

    def load(self):
        if self.single:
            return self
        self.fetch_groups()
        self.select(self.quality_name)
        return self

    def episodes(self) -> Dict[int, str]:
        if not self._loaded:
            self.load()
        return {k: (self._labels.get(k) or f'Episode {k}')
                for k in sorted(self._eps)}

    def size(self, num: int) -> int:
        """File size in bytes for `num` (probes the signed CDN link once,
        then caches; 0 when unknown/unprobed)."""
        try:
            if not self._loaded:
                self.load()
            if num not in self._eps:
                return 0
            if self._sizes.get(num) is None:
                src = HttpSource(self._eps[num], headers=hdrs(self._cs),
                                 http=self.http)
                self._sizes[num] = src.size or 0
            return int(self._sizes.get(num) or 0)
        except Exception:
            return 0

    def stream(self, num: int) -> HttpSource:
        if not self._loaded:
            self.load()
        try:
            e = fetch_eps_window(self._aid, self._gid, num, num,
                                 self._csrf, self._cs, self.http)
            link = e[0]['link'] if e else self._eps.get(num)
        except Exception:
            link = self._eps.get(num)
        if not link:
            raise KeyError(f'no link for episode {num}')
        return HttpSource(link, hdrs(self._cs, {'Referer': BASE + '/'}),
                          self.http)


def search(query: str, http=None, cookies=None, limit: int = 12) -> List[dict]:
    """AnimeGate search -> [{'title','url','source'}]. Works logged-out too."""
    q = (query or '').strip()
    if not q:
        return []
    http = http or HttpClient()
    try:
        cs = cookies if cookies is not None else firefox_cookies()
    except Exception:
        cs = {}
    extra = {'Accept': 'application/json',
             'X-Requested-With': 'XMLHttpRequest'}
    u = f'{BASE}/global-search?s={urllib.parse.quote(q)}'
    r = http.open(http.request(u, headers=hdrs(cs, extra)))
    try:
        d = json.loads(r.read().decode('utf-8', 'replace'))
    finally:
        _quiet_close(r)
    out: List[dict] = []
    for grp in d.get('types') or []:
        for it in (grp.get('items') or []):
            url, title = it.get('url'), it.get('title')
            if url and title:
                out.append({'title': str(title), 'url': str(url),
                            'source': 'agp'})
            if len(out) >= limit:
                return out
    return out
