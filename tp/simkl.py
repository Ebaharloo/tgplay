"""tp.simkl - Simkl episode titles (a fallback for donghua, where Jikan/MAL and
AniList often have no episode names).

Needs a free Simkl client_id: set `AGP_SIMKL_CLIENT_ID`, or
`~/.config/tgp/simkl.json` = {"client_id": "..."}. Without one every call is a
silent no-op.

Flow: MAL/AniList id (or a title) -> Simkl id via /search/id -> episode list via
/anime/episodes/{id} -> {episode number: title}.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional

from .http import HttpClient, _quiet_close

API = 'https://api.simkl.com'
CONF = os.path.expanduser('~/.config/tgp/simkl.json')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _dig(obj, key):
    """Pull `key` out of ids{...} from a Simkl search/redirect response."""
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    if isinstance(obj, dict):
        ids = obj.get('ids') or {}
        if key in ids:
            return ids[key]
        if key in obj:
            return obj[key]
    return None


class Simkl:
    def __init__(self, client_id: Optional[str] = None,
                 http: Optional[HttpClient] = None):
        self.client_id = (client_id or os.environ.get('AGP_SIMKL_CLIENT_ID')
                          or self._file_id())
        self.http = http or HttpClient(timeout=25)
        self._ids: Dict[tuple, Optional[int]] = {}
        self._eps: Dict[int, Dict[int, str]] = {}

    @staticmethod
    def _file_id() -> Optional[str]:
        try:
            return json.load(open(CONF)).get('client_id')
        except Exception:
            return None

    def available(self) -> bool:
        return bool(self.client_id)

    def _get(self, path, **params):
        params['client_id'] = self.client_id
        url = f'{API}{path}?{urllib.parse.urlencode(params)}'
        r = self.http.open(self.http.request(url))
        try:
            return json.load(r)
        finally:
            _quiet_close(r)

    def _redirect(self, **params) -> Optional[int]:
        """Resolve via GET /redirect (works WITHOUT a client_id): read the
        Location header, e.g. .../anime/2158326/zhe-tian -> 2158326."""
        params['to'] = 'anime'
        url = f'{API}/redirect?{urllib.parse.urlencode(params)}'
        try:
            _OPENER.open(url, timeout=15)
        except urllib.error.HTTPError as e:
            loc = (e.headers.get('Location') or '') if e.headers else ''
            m = re.search(r'/(?:anime|tv)/(\d+)', loc)
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


def save_client_id(client_id: str):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    json.dump({'client_id': client_id}, open(CONF, 'w'))
