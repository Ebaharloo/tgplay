"""tp.simkl - Simkl episode titles (a fallback for donghua, where Jikan/MAL and
AniList often have no episode names).

Needs a free Simkl client_id: set `AGP_SIMKL_CLIENT_ID`, or
`~/.config/tgp/simkl.json` = {"client_id": "..."}. Without one every call is a
silent no-op.

Flow: MAL/AniList id (or a title) -> Simkl id via /redirect (canonical, keyless;
/search/id is the keyed fallback) -> episode list via /anime/episodes/{id} ->
{episode number: title}. `identify(path)` names a local video file via
POST /search/file (needs the user token).
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, Optional

from .http import HttpClient, _quiet_close

API = 'https://api.simkl.com'
APP, VER = 'tgplay', '1.0'
CONF = os.path.expanduser('~/.config/tgp/simkl.json')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _dig(obj, key):
    """Pull `key` out of ids{...} from a Simkl search/redirect response.

    The API names it inconsistently: /redirect & /search/id use 'simkl',
    /search/anime uses 'simkl_id' - accept both (missing this made
    title-query resolve silently return None)."""
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    if isinstance(obj, dict):
        ids = obj.get('ids') or {}
        for k in (key, f'{key}_id'):
            if k in ids:
                return ids[k]
        if key in obj:
            return obj[key]
    return None


class Simkl:
    def __init__(self, client_id: Optional[str] = None,
                 http: Optional[HttpClient] = None, auth_fn: Callable = None):
        self.client_id = (client_id or os.environ.get('AGP_SIMKL_CLIENT_ID')
                          or self._file_id())
        self.http = http or HttpClient(timeout=25)
        self.auth_fn = auth_fn      # -> 'Bearer <token>' when the user logged in
        self._ids: Dict[tuple, Optional[int]] = {}
        self._eps: Dict[int, Dict[int, str]] = {}
        self._records: Dict[int, Optional[dict]] = {}
        self._files: Dict[str, Optional[dict]] = {}

    @staticmethod
    def _file_id() -> Optional[str]:
        try:
            return json.load(open(CONF)).get('client_id')
        except Exception:
            return None

    def available(self) -> bool:
        return bool(self.client_id)

    def _auth(self) -> dict:
        """The Bearer header user-scoped endpoints need (none when logged out)."""
        if not self.auth_fn:
            return {}
        try:
            auth = self.auth_fn()
        except Exception:
            return {}
        return {'Authorization': auth} if auth else {}

    def _url(self, path, **params) -> str:
        params.update({'client_id': self.client_id,
                       'app-name': APP, 'app-version': VER})
        return f'{API}{path}?{urllib.parse.urlencode(params)}'

    def _get(self, path, **params):
        r = self.http.open(self.http.request(self._url(path, **params),
                                             headers=self._auth()))
        try:
            return json.load(r)
        finally:
            _quiet_close(r)

    def _post(self, path, body):
        h = self._auth()
        h['Content-Type'] = 'application/json'
        r = self.http.open(self.http.request(
            self._url(path), headers=h, method='POST',
            data=json.dumps(body).encode()))
        try:
            return json.load(r)
        finally:
            _quiet_close(r)

    def _redirect(self, **params) -> Optional[int]:
        """Resolve via GET /redirect (works WITHOUT a client_id): read the
        Location header, e.g. .../anime/2158326/zhe-tian -> 2158326."""
        params['to'] = 'simkl'
        url = f'{API}/redirect?{urllib.parse.urlencode(params)}'
        req = urllib.request.Request(url, headers={'User-Agent': f'{APP}/{VER}'})
        try:
            _OPENER.open(req, timeout=15)
        except urllib.error.HTTPError as e:
            loc = (e.headers.get('Location') or '') if e.headers else ''
            m = re.search(r'/(?:anime|tv|movies)/(\d+)', loc)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return None

    def resolve(self, mal=None, anilist=None, query=None) -> Optional[int]:
        key = ('mal', mal) if mal else (('anilist', anilist) if anilist
                                        else ('q', query))
        if key in self._ids:
            return self._ids[key]
        sid = None
        try:
            if mal or anilist:
                # /redirect needs no key; /search/id is the keyed fallback
                sid = self._redirect(**({'mal': mal} if mal
                                        else {'anilist': anilist}))
                if sid is None and self.client_id:
                    d = self._get('/search/id',
                                  **({'mal': mal} if mal
                                     else {'anilist': anilist}))
                    sid = _dig(d, 'simkl')
            elif query and self.client_id:
                sid = _dig(self._get('/search/anime', q=query), 'simkl')
        except Exception:
            sid = None
        self._ids[key] = sid
        return sid

    def episodes(self, simkl_id: int) -> Dict[int, str]:
        if simkl_id in self._eps:
            return self._eps[simkl_id]
        out: Dict[int, str] = {}
        try:
            data = self._get(f'/anime/episodes/{simkl_id}')
            for e in (data or []):
                n = e.get('episode')
                t = e.get('title')
                if isinstance(n, int) and t:
                    out[n] = t
        except Exception:
            pass
        self._eps[simkl_id] = out
        return out

    def episode_title(self, ep: int, mal=None, anilist=None,
                      query=None) -> Optional[str]:
        sid = self.resolve(mal=mal, anilist=anilist, query=query)
        if not sid:
            return None
        return self.episodes(sid).get(int(ep))

    # --- local file identify (POST /search/file) ----------------------------
    def identify(self, path: str) -> Optional[dict]:
        """Name one local video file: {'type', 'title', 'season', 'episode',
        'ids'} or None when Simkl has no match.

        Needs the user token: the shipped client_id is a device app and 401s
        on this endpoint. One file at a time - Simkl throttles library scans.
        """
        name = os.path.basename(str(path or '').replace('\\', '/'))
        if not name:
            return None
        if name in self._files:
            return self._files[name]
        rec = None
        try:
            d = self._post('/search/file', {'file': name})
        except Exception:
            d = None
        if isinstance(d, dict):                  # null / [] = no match
            show = d.get('show') or d.get('movie') or {}
            if show:                              # malformed match -> no match
                ep = d.get('episode') or {}
                rec = {'type': d.get('type'), 'title': show.get('title'),
                       'season': ep.get('season'), 'episode': ep.get('episode'),
                       'ids': show.get('ids') or {}}
        self._files[name] = rec
        return rec

    # --- anime record + page link (keyless) --------------------------------
    def info(self, mal=None, anilist=None, query=None) -> Optional[dict]:
        sid = self.resolve(mal=mal, anilist=anilist, query=query)
        if not sid:
            return None
        if sid in self._records:
            return self._records[sid]
        try:
            rec = self._get(f'/anime/{sid}')
        except Exception:
            rec = None
        self._records[sid] = rec
        return rec

    @staticmethod
    def page_url(info: dict) -> Optional[str]:
        ids = (info or {}).get('ids') or {}
        sid, slug = ids.get('simkl'), ids.get('slug')
        if not sid:
            return None
        return f'https://simkl.com/anime/{sid}/{slug or ""}'.rstrip('/')

    def show_link(self, mal=None, anilist=None, query=None) -> Optional[str]:
        """The anime's Simkl page URL (keyless; None when not found)."""
        return self.page_url(self.info(mal=mal, anilist=anilist, query=query))


def save_client_id(client_id: str):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    json.dump({'client_id': client_id}, open(CONF, 'w'))
