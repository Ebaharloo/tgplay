"""tp.simkl_account - the user's Simkl account (AUTH V2 device flow).

Simkl is our **tracking hub**: it two-way-syncs with MAL, AniList, Kitsu, Trakt
and more, so keeping Simkl in sync keeps every other platform in sync too.

Flow (device / PIN, ideal for a CLI):
    POST /oauth2/device   -> user_code + verification_uri_complete
    (user approves at simkl.com/pin)
    POST /oauth2/token    -> access_token + refresh_token   (poll)

Then: GET /sync/all-items/anime (the library) and POST /sync/history (progress).

Requires a **V2** client_id (V1 ids are rejected with 401 invalid_client);
register at https://simkl.com/settings/developer/ and set it with
`agp simkl <CLIENT_ID>` (shared with the metadata lookup).
"""
import json
import os
import time
import urllib.parse
from typing import Dict, List, Optional

from .http import HttpClient, _quiet_close

API = 'https://api.simkl.com'
APP = 'tgplay'
VER = '1.0'


def _read(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def _write(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(d, open(path, 'w'))


def _client_id(cfg) -> Optional[str]:
    cid = os.environ.get('AGP_SIMKL_CLIENT_ID')
    if cid:
        return cid
    try:
        return json.load(open(os.path.join(os.path.dirname(cfg.progress),
                                           'simkl.json'))).get('client_id')
    except Exception:
        return None


class SimklAccount:
    def __init__(self, cfg, http: Optional[HttpClient] = None):
        self.cfg = cfg
        self.http = http or HttpClient(timeout=25)
        self.client_id = _client_id(cfg)

    # --- tokens ---------------------------------------------------------
    def _auth(self) -> dict:
        return _read(self.cfg.simkl_auth, {})

    def _save(self, **kw):
        a = self._auth()
        a.update(kw)
        _write(self.cfg.simkl_auth, a)
        return a

    def access_token(self) -> Optional[str]:
        return os.environ.get('AGP_SIMKL_TOKEN') or self._auth().get('access_token')

    def logged_in(self) -> bool:
        return bool(self.access_token() and self.client_id)

    # --- low level ------------------------------------------------------
    def _form(self, path: str, data: Dict[str, str]) -> dict:
        body = urllib.parse.urlencode(data).encode()
        req = self.http.request(f'{API}{path}', method='POST',
                                headers={'Content-Type':
                                         'application/x-www-form-urlencoded',
                                         'User-Agent': f'{APP}/{VER}'},
                                data=body)
        try:
            r = self.http.open(req)
        except Exception as ex:
            return {'error': str(ex)}
        try:
            return json.load(r)
        finally:
            _quiet_close(r)

    def _api(self, path: str, params: Dict[str, str] = None,
             method: str = 'GET', body=None) -> dict:
        p = dict(params or {})
        p.update({'client_id': self.client_id, 'app-name': APP,
                  'app-version': VER})
        url = f'{API}{path}?{urllib.parse.urlencode(p)}'
        headers = {'User-Agent': f'{APP}/{VER}', 'Accept': 'application/json'}
        if self.access_token():
            headers['Authorization'] = 'Bearer ' + self.access_token()
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        req = self.http.request(url, method=method, headers=headers, data=data)
        r = self.http.open(req)
        try:
            return json.load(r)
        finally:
            _quiet_close(r)

    # --- login (device / PIN) ------------------------------------------
    def login(self, poll_limit: int = 180) -> Optional[dict]:
        if not self.client_id:
            print('simkl: no client_id. Register a V2 app at '
                  'https://simkl.com/settings/developer/ then run:\n'
                  '  agp simkl <CLIENT_ID>')
            return None
        d = self._form('/oauth2/device',
                       {'client_id': self.client_id,
                        'scope': 'media:read media:write'})
        if d.get('error') or not d.get('device_code'):
            print(f"simkl: device auth failed ({d.get('error') or d}). "
                  'A V1 client_id cannot use this flow - register a V2 app.')
            return None
        code = d.get('user_code', '')
        url = d.get('verification_uri_complete') or 'https://simkl.com/pin'
        print('simkl: open this and approve, then come back here:')
        print(f'  {url}')
        print(f'  (code: {code})')
        interval = int(d.get('interval') or 5)
        deadline = time.time() + min(poll_limit, int(d.get('expires_in') or 900))
        while time.time() < deadline:
            time.sleep(interval)
            tok = self._form('/oauth2/token', {
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'client_id': self.client_id, 'device_code': d['device_code']})
            if tok.get('access_token'):
                self._save(client_id=self.client_id,
                           access_token=tok['access_token'],
                           refresh_token=tok.get('refresh_token'),
                           scope=tok.get('scope'),
                           at=int(time.time()))
                who = self.user()
                print(f"simkl: connected{(' as ' + who) if who else ''}")
                return tok
            err = tok.get('error')
            if err == 'authorization_pending':
                continue
            if err == 'slow_down':
                interval += 5
                continue
            if err in ('expired_token', 'invalid_client'):
                print(f'simkl: {err} - start again')
                return None
        print('simkl: timed out waiting for approval')
        return None

    def refresh(self) -> Optional[str]:
        a = self._auth()
        rt = a.get('refresh_token')
        if not rt:
            return None
        d = self._form('/oauth2/token', {
            'grant_type': 'refresh_token', 'client_id': self.client_id,
            'refresh_token': rt})
        if d.get('access_token'):
            self._save(access_token=d['access_token'],
                       refresh_token=d.get('refresh_token') or rt,
                       at=int(time.time()))
            return d['access_token']
        return None

    def logout(self):
        try:
            os.remove(self.cfg.simkl_auth)
            print('simkl: disconnected')
        except OSError:
            print('simkl: not connected')

    # --- library --------------------------------------------------------
    def user(self) -> Optional[str]:
        try:
            d = self._api('/users/settings', method='POST')
            u = d.get('user') or d
            return u.get('name') or u.get('username') or u.get('id')
        except Exception:
            return None

    def _items(self, type_: str = 'anime', status: Optional[str] = None,
               extra: Dict[str, str] = None) -> List[dict]:
        path = f'/sync/all-items/{type_}'
        if status:
            path += f'/{status}'
        params = {'next_watch_info': 'yes', 'language': 'en'}
        params.update(extra or {})
        try:
            d = self._api(path, params)
        except Exception:
            return []
        # response is either {status: [items]} or [items]
        rows: List[dict] = []
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, dict):
                            it.setdefault('status', k)
                            rows.append(it)
        elif isinstance(d, list):
            rows = [x for x in d if isinstance(x, dict)]
        return rows

    @staticmethod
    def _norm(it: dict) -> dict:
        show = it.get('show') or it
        ids = show.get('ids') or it.get('ids') or {}
        nxt = it.get('next_to_watch_info') or {}
        next_ep = nxt.get('episode')
        if next_ep is None and it.get('next_to_watch'):
            import re
            m = re.search(r'(\d+)\s*$', str(it['next_to_watch']))
            next_ep = int(m.group(1)) if m else None
        return {
            'title': show.get('title') or it.get('title') or '',
            'simkl': ids.get('simkl'),
            'mal': ids.get('mal'),
            'anilist': ids.get('anilist'),
            'status': it.get('status'),
            'watched': it.get('watched_episodes_count') or 0,
            'total': it.get('total_episodes_count') or 0,
            'next_ep': next_ep,
            'poster': show.get('poster') or it.get('poster'),
        }

    def library(self, statuses=('watching', 'plantowatch')) -> List[dict]:
        out: List[dict] = []
        for st in statuses:
            for it in self._items('anime', st):
                out.append(self._norm(it))
        return out

    def up_next(self) -> List[dict]:
        return [e for e in self.library(('watching',))
                if e.get('next_ep') and e['title']]

    # --- progress -------------------------------------------------------
    def mark_watched(self, entry: dict, ep: int) -> bool:
        """Best-effort: record episode `ep` watched for a library entry."""
        if not self.logged_in():
            return False
        ids = {}
        for k in ('mal', 'anilist', 'simkl'):
            if entry.get(k):
                ids[k] = entry[k]
        if not ids:
            return False
        body = {'anime': [{'ids': ids,
                           'seasons': [{'number': 1,
                                        'episodes': [{'number': int(ep)}]}]}]}
        try:
            self._api('/sync/history', method='POST', body=body)
            return True
        except Exception:
            return False


class SimklTracker:
    """Playlist-compatible tracker: pushes finished episodes to Simkl.

    Matches a playing title to a library entry (fuzzy) and records progress, so
    Simkl (and everything it syncs with) stays current.
    """

    def __init__(self, cfg, http: Optional[HttpClient] = None):
        self.acc = SimklAccount(cfg, http)
        self._entries: Optional[List[dict]] = None

    def enabled(self) -> bool:
        return self.acc.logged_in()

    def _match(self, title: str) -> Optional[dict]:
        if self._entries is None:
            self._entries = self.acc.library()
        want = (title or '').casefold()
        best, score = None, 0.0
        import difflib
        for e in self._entries:
            r = difflib.SequenceMatcher(None, want,
                                        e['title'].casefold()).ratio()
            if r > score:
                best, score = e, r
        return best if score >= 0.6 else None

    def mark_watched(self, title, num, ask=False):
        e = self._match(title)
        return self.acc.mark_watched(e, num) if e else None
