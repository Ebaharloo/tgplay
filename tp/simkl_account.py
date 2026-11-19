"""tp.simkl_account - the user's Simkl account: auth, library, watched sync.

Simkl is our **tracking hub**: it two-way-syncs with MAL, AniList, Kitsu, Trakt
and more, so keeping Simkl in sync keeps every other platform in sync too.

Flow (device / PIN, ideal for a CLI):
    POST /oauth2/device   -> user_code + verification_uri_complete
    (user approves at simkl.com/pin)
    POST /oauth2/token    -> access_token + refresh_token   (poll)

Then: GET /sync/all-items/anime (the library) and POST /sync/history (progress).

client_id (required) is resolved in this order:
    1. `AGP_SIMKL_CLIENT_ID` environment variable
    2. `client_id` in `~/.config/tgp/simkl.json` (next to the progress file)
    3. `BUILTIN_CLIENT_ID` below - shared by every user of the app
Set it with `agp simkl <CLIENT_ID>`. Register a **V2** app at
https://simkl.com/settings/developer/ (V1 ids are rejected with 401
invalid_client). Tokens live in `cfg.simkl_auth`; an expired access token
refreshes itself before the call.

Auth is AUTH V2 (RFC 8628 device flow: POST /oauth2/device, then
/oauth2/token). The V1 `/oauth/pin` endpoints are retired around April 2027,
so this client uses V2 only.

Every public method returns parsed JSON or raises `SimklError`.
"""
import json
import os
import time
import urllib.error
import urllib.parse
from typing import Dict, List, Optional

from .http import HttpClient, _quiet_close

API = 'https://api.simkl.com'
APP = 'tgplay'
VER = '1.0'
RETRIES = 3             # extra attempts for 429 / 5xx, on top of the first try
RATE_WAIT_CAP = 60      # a longer 429 Retry-After is the daily quota: report it
SCROBBLE = ('start', 'pause', 'stop')
STATUSES = ('watching', 'plantowatch', 'completed', 'hold', 'dropped')


class SimklError(Exception):
    """A failed Simkl call. `status` is the HTTP code, `error` the stable
    machine field from the body (`rate_limit`, `id_err`, ...)."""

    def __init__(self, message, status=None, error=None, payload=None):
        super().__init__(message)
        self.status = status
        self.error = error
        self.payload = payload or {}


# No client_id ships with the app: register your own once at
# https://simkl.com/settings/developer/ (client type "TV, devices & command
# line") and hand it over with `tgplay simkl <client_id>` (stored in
# ~/.config/tgp/simkl.json) or AGP_SIMKL_CLIENT_ID.
BUILTIN_CLIENT_ID = ''


def _read(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def _write(path, d):
    from .config import save_json
    save_json(path, d)


def _client_id(cfg) -> Optional[str]:
    cid = (os.environ.get('AGP_SIMKL_CLIENT_ID')
           or _read(os.path.join(os.path.dirname(cfg.progress), 'simkl.json'),
                    {}).get('client_id')
           or BUILTIN_CLIENT_ID)
    return cid or None


def _body(ex: urllib.error.HTTPError):
    """(error, payload) from an HTTPError body; never raises.

    The body is consumed here, so callers must not read `ex` again."""
    try:
        payload = json.loads(ex.read() or b'{}')
    except Exception:
        return None, {}
    if not isinstance(payload, dict):
        return None, {}
    return payload.get('error'), payload


def _want_wait(ex: urllib.error.HTTPError, err: Optional[str]) -> float:
    """Seconds the server asked us to wait before retrying this request.

    A bare `rate_limit` 429 is the per-second cap (~1 s), not the daily quota -
    its Retry-After carries the daily reset, so ignore the header for it.
    Returns 0 when the answer is "use exponential backoff"."""
    if err == 'rate_limit':
        return 1.0
    try:
        return float(ex.headers.get('Retry-After') or 0)
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _rows(d) -> List[dict]:
    """Flatten a /sync/all-items response: {status: [items]} or [items]."""
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


def _wanted(show_ids) -> set:
    """Every id value from one ids dict or a list of them."""
    one = show_ids if isinstance(show_ids, (list, tuple)) else [show_ids]
    return {str(v) for ids in one if isinstance(ids, dict)
            for v in ids.values() if v}


def _expires_at(tok: dict) -> Optional[int]:
    """Absolute expiry from an OAuth token response (None when not advertised)."""
    try:
        return int(time.time()) + int(tok.get('expires_in'))
    except (TypeError, ValueError):
        return None


def _row_key(r: dict) -> str:
    """Cache key for one /sync/all-items row, best id first."""
    show = r.get('show') or r
    ids = show.get('ids') or {}
    return str(ids.get('simkl') or ids.get('mal') or show.get('title') or '')


def _merge(old: List[dict], new: List[dict]) -> List[dict]:
    """A date_from delta laid over the cached rows."""
    out = {_row_key(r): r for r in old}
    out.update({_row_key(r): r for r in new})
    return list(out.values())


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

    def _expired(self) -> bool:
        """True when the saved access token is past (or near) its expiry.

        ACCESS tokens last 7 days (AUTH V2); `expires_at` is saved at login and
        on every refresh. Missing `expires_at` (older installs) = not expired,
        the 401 path still refreshes.
        """
        exp = self._auth().get('expires_at')
        try:
            return bool(exp) and time.time() >= float(exp) - 60
        except (TypeError, ValueError):
            return False

    def logged_in(self) -> bool:
        return bool(self.access_token() and self.client_id)

    # --- low level ------------------------------------------------------
    def _form(self, path: str, data: Dict[str, str], timeout=None,
              tries=None) -> dict:
        body = urllib.parse.urlencode(data).encode()
        req = self.http.request(f'{API}{path}', method='POST',
                                headers={'Content-Type':
                                         'application/x-www-form-urlencoded',
                                         'User-Agent': f'{APP}/{VER}'},
                                data=body)
        try:
            r = self.http.open(req, timeout=timeout, tries=tries)
        except Exception as ex:
            return {'error': str(ex)}
        try:
            try:
                return json.load(r)
            except ValueError:
                return {}     # 200 with an empty body (RFC 7009 revoke)
        finally:
            _quiet_close(r)

    def _api(self, path: str, params: Dict[str, str] = None,
             method: str = 'GET', body=None, retries: Optional[int] = None) -> dict:
        p = dict(params or {})
        p.update({'client_id': self.client_id, 'app-name': APP,
                  'app-version': VER})
        url = f'{API}{path}?{urllib.parse.urlencode(p)}'
        headers = {'User-Agent': f'{APP}/{VER}', 'Accept': 'application/json'}
        if self.client_id:
            headers['simkl-api-key'] = self.client_id
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'

        def send():
            h = dict(headers)
            if self.access_token():
                h['Authorization'] = 'Bearer ' + self.access_token()
            return self.http.open(
                self.http.request(url, method=method, headers=h, data=data))

        n = RETRIES if retries is None else retries
        r = None
        for attempt in range(n + 1):
            # expired token -> refresh before sending (401 below is the fallback)
            if attempt == 0 and self._expired():
                self.refresh()
            try:
                r = send()
                break
            except urllib.error.HTTPError as ex:
                err, payload = _body(ex)
                # 401 = expired/revoked access token: refresh ONCE and retry.
                # This is what keeps the calendar/remaining working without a
                # manual re-login.
                if ex.code == 401 and attempt == 0 and self.refresh():
                    continue
                wait = _want_wait(ex, err)
                if attempt < n and (ex.code in (500, 502, 503)
                                    or (ex.code == 429
                                        and wait <= RATE_WAIT_CAP)):
                    time.sleep(wait or min(0.5 * 2 ** attempt, 30))
                    continue
                raise SimklError(
                    f'simkl {ex.code} {path}: '
                    f'{payload.get("message") or err or ex.reason}',
                    status=ex.code, error=err, payload=payload) from ex
        try:
            return json.load(r)
        except ValueError:
            return {}      # 204: DELETE /sync/playback/{id} sends no body
        finally:
            _quiet_close(r)

    # --- login (device / PIN) ------------------------------------------
    def start_device(self) -> Optional[dict]:
        """Begin the PIN flow for a GUI/worker: url + code to show the user.

        Returns {'url','code','device_code','interval','expires'} or None."""
        if not self.client_id:
            return None
        d = self._form('/oauth2/device',
                       {'client_id': self.client_id,
                        'scope': 'media:read media:write'})
        if d.get('error') or not d.get('device_code'):
            return None
        return {'url': d.get('verification_uri_complete')
                       or 'https://simkl.com/pin',
                'code': d.get('user_code', ''),
                'device_code': d['device_code'],
                'interval': int(d.get('interval') or 5),
                'expires': int(d.get('expires_in') or 900)}

    def poll_device(self, device_code: str) -> str:
        """One poll: 'ok' (saved), 'pending', or the error string."""
        tok = self._form('/oauth2/token', {
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            'client_id': self.client_id, 'device_code': device_code})
        if tok.get('access_token'):
            self._save(client_id=self.client_id,
                       access_token=tok['access_token'],
                       refresh_token=tok.get('refresh_token'),
                       scope=tok.get('scope'), at=int(time.time()),
                       expires_at=_expires_at(tok))
            return 'ok'
        err = tok.get('error')
        return err or 'pending'

    def login(self, poll_limit: int = 180) -> Optional[dict]:
        if not self.client_id:
            print('simkl: no client_id configured.')
            print('  Maintainer (once): register a V2 app at '
                  'https://simkl.com/settings/developer/')
            print('  client type "TV, devices & command line" '
                  '(no redirect URI needed), then share it:')
            print('    agp simkl <CLIENT_ID>   '
                  '(or AGP_SIMKL_CLIENT_ID, or BUILTIN_CLIENT_ID in '
                  'tp/simkl_account.py)')
            print('  Users then only run: tgplay simkl login')
            return None
        dev = self.start_device()
        if not dev:
            print('simkl: device auth failed. A V1 client_id cannot use '
                  'this flow - register a V2 app.')
            return None
        print('simkl: open this and approve, then come back here:')
        print(f"  {dev['url']}")
        print(f"  (code: {dev['code']})")
        interval = dev['interval']
        deadline = time.time() + min(poll_limit, dev['expires'])
        while time.time() < deadline:
            time.sleep(interval)
            res = self.poll_device(dev['device_code'])
            if res == 'ok':
                who = self.user()
                print(f"simkl: connected{(' as ' + who) if who else ''}")
                return {'ok': True}
            if res == 'pending':
                continue
            if res == 'slow_down':
                interval += 5
                continue
            if res in ('expired_token', 'invalid_client'):
                print(f'simkl: {res} - start again')
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
                       at=int(time.time()), expires_at=_expires_at(d))
            return d['access_token']
        return None

    def revoke(self) -> bool:
        """POST /oauth2/revoke: kill the grant on the server (both tokens).

        RFC 7009: 200 even for a dead token, so a False answer means the call
        itself failed and the token stays usable until it expires."""
        a = self._auth()
        tok = a.get('refresh_token') or a.get('access_token')
        if not (tok and self.client_id):
            return False
        d = self._form('/oauth2/revoke', {'client_id': self.client_id,
                                          'token': tok},
                       timeout=5, tries=1)   # a logout must not hang the UI
        return not d.get('error')

    def logout(self):
        a = self._auth()
        tok = a.get('refresh_token') or a.get('access_token')
        if tok and not self.revoke():
            print('simkl: server revoke failed - token stays valid until it '
                  'expires')
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

    def stats(self, user_id: Optional[int] = None) -> dict:
        """GET /users/{id}/stats: total minutes, per-catalog counts.

        Simkl computes this live over the whole history (their most expensive
        call, so call it on an explicit action only - never on a timer."""
        if user_id is None:
            d = self._api('/users/settings', method='POST')
            user_id = ((d.get('account') or {}).get('id')
                       or (d.get('user') or {}).get('id'))
        if not user_id:
            raise SimklError('simkl: no user id for stats')
        return self._api(f'/users/{int(user_id)}/stats')

    def _items(self, type_: str = 'anime', status: Optional[str] = None,
               extra: Optional[Dict[str, str]] = None) -> List[dict]:
        """One /sync/all-items call, flattened. Raises `SimklError`."""
        path = f'/sync/all-items/{type_}'
        if status:
            path += f'/{status}'
        params = {'next_watch_info': 'yes', 'language': 'en'}
        params.update(extra or {})
        return _rows(self._api(path, params))

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
            'air_date': nxt.get('date'),
            'last_watched': it.get('last_watched_at'),
            'poster': show.get('poster') or it.get('poster'),
        }

    def library(self, statuses=('watching', 'plantowatch')) -> List[dict]:
        """The anime library: one full pull, then only the delta.

        Simkl's two-phase rule (apps that poll the full library get their
        client_id suspended): `/sync/activities` is the gate, `date_from` is
        the saved `all` stamp, so a poll with nothing new costs one tiny call.
        A failed delta keeps the cached rows AND their stamp, so the same
        delta is fetched again next time instead of being lost.

        shortcut: a delta never reports a removal from a list, so a title
        dropped elsewhere stays in the cache until simkl_library.json is
        deleted; add an ids_only diff if that ever matters.
        """
        path = self.cfg.simkl_library
        cache = _read(path, {})
        cache = cache if isinstance(cache, dict) else {}
        old = cache.get('rows') or []
        try:
            stamp = str((self.activities() or {}).get('all') or '')
        except Exception:
            stamp = ''
        rows = old
        save = False
        if not (old and stamp and stamp == cache.get('all')):
            since = cache.get('all') if (old and cache.get('all')) else None
            try:
                got = self._items('anime', extra={'date_from': since}
                                  if since else None)
            except Exception:
                got = None            # keep cache + stamp: retry this delta
            if got is not None:
                rows, save = (_merge(old, got) if since else got), True
        if save:
            try:
                _write(path, {'all': stamp or cache.get('all'), 'rows': rows})
            except Exception:
                pass                  # a read-only home still yields rows
        if statuses:
            rows = [r for r in rows if r.get('status') in statuses]
        return [self._norm(r) for r in rows]

    def up_next(self) -> List[dict]:
        return [e for e in self.library(('watching',))
                if e.get('next_ep') and e['title']]

    # --- progress -------------------------------------------------------
    def _history(self, ids: dict, season=None, episode=None,
                 remove: bool = False) -> dict:
        """POST /sync/history[/remove] for one show, at the level asked for.

        The payload shape IS the level: an episode carries
        seasons[].episodes[], a season drops `episodes`, the whole show drops
        `seasons` (Simkl then marks every aired episode)."""
        if not ids:
            raise SimklError('simkl: no ids for history call')
        entry = {'ids': dict(ids)}
        if season is not None:
            s: Dict[str, object] = {'number': int(season)}
            if episode is not None:
                s['episodes'] = [{'number': int(episode)}]
            entry['seasons'] = [s]
        return self._api('/sync/history/remove' if remove else '/sync/history',
                         method='POST', body={'anime': [entry]})

    def mark_episode_watched(self, show_ids: dict, season, episode) -> dict:
        return self._history(show_ids, season, episode)

    def unmark_episode_watched(self, show_ids: dict, season, episode) -> dict:
        return self._history(show_ids, season, episode, remove=True)

    def mark_season_watched(self, show_ids: dict, season) -> dict:
        return self._history(show_ids, season)

    def unmark_season_watched(self, show_ids: dict, season) -> dict:
        return self._history(show_ids, season, remove=True)

    def mark_show_complete(self, show_ids: dict) -> dict:
        return self._history(show_ids)

    def unmark_show_complete(self, show_ids: dict) -> dict:
        return self._history(show_ids, remove=True)

    def get_watched(self, show_ids=None) -> List[dict]:
        """Watched state per show, with per-episode rows.

        `show_ids` is one ids dict ({'mal': 1}) or a list of them; None returns
        the whole anime library. Rows are the raw `/sync/all-items/anime` items
        (show.ids, status, watched_episodes_count, seasons[].episodes[])."""
        rows = _rows(self._api('/sync/all-items/anime', {
            'extended': 'full', 'include_all_episodes': 'original',
            'episode_watched_at': 'yes', 'language': 'en'}))
        want = _wanted(show_ids)
        if not want:
            return rows

        def hit(it):
            ids = (it.get('show') or it).get('ids') or it.get('ids') or {}
            return any(str(ids.get(k)) in want for k in ('simkl', 'mal',
                                                         'anilist'))
        return [r for r in rows if hit(r)]

    def watched(self, show_ids=None, per_call: int = 100) -> List[dict]:
        """POST /sync/watched: per-episode watched state for titles you name.

        Bulk replacement for `get_watched`: one call covers up to 100 shows
        and returns only their episodes, instead of downloading the whole
        library with every episode. `show_ids` is one ids dict or a list of
        them. Rows carry `seasons[].episodes[]` ({number, watched, aired,
        last_watched_at}); ids Simkl cannot match come back as `not_found`
        with no seasons and are dropped here.
        """
        one = [show_ids] if isinstance(show_ids, dict) else list(show_ids or [])
        one = [i for i in one if isinstance(i, dict) and i]
        out: List[dict] = []
        for i in range(0, len(one), per_call):
            d = self._api('/sync/watched', {'extended': 'episodes'},
                          method='POST',
                          body=[{'ids': dict(ids)}
                                for ids in one[i:i + per_call]])
            out += [r for r in (d if isinstance(d, list) else [])
                    if isinstance(r, dict) and r.get('seasons')]
        return out

    def mark_watched(self, entry: dict, ep: int) -> int:
        """Record episode `ep` watched; returns how many episodes Simkl added
        (0 when it was already watched)."""
        if not self.logged_in():
            return 0
        ids = {k: entry[k] for k in ('mal', 'anilist', 'simkl')
               if entry.get(k)}
        if not ids:
            return 0
        d = self.mark_episode_watched(ids, 1, ep)
        return int(((d.get('added') or {}).get('episodes')) or 0)

    def add_to_list(self, ids: dict, status: str = 'watching') -> bool:
        """Put a title on a Simkl watchlist status (so it shows in the feed)."""
        if status not in STATUSES:
            raise ValueError(f'unknown list status {status!r}')
        if not self.logged_in() or not ids:
            return False
        body = {'anime': [{'ids': ids, 'to': status}]}
        try:
            self._api('/sync/add-to-list', method='POST', body=body)
            return True
        except Exception:
            return False

    def rate(self, ids: dict, rating) -> bool:
        """POST /sync/ratings, 1-10. Simkl drops an out-of-range value without
        saying so, so it is refused here instead."""
        if not ids:
            return False
        n = int(rating)
        if not 1 <= n <= 10:
            raise ValueError(f'rating must be 1-10, got {rating!r}')
        if not self.logged_in():
            return False
        self._api('/sync/ratings', method='POST',
                  body={'anime': [{'ids': dict(ids), 'rating': n}]})
        return True

    def unrate(self, ids: dict) -> bool:
        """POST /sync/ratings/remove: clear a score; the title stays listed."""
        if not ids or not self.logged_in():
            return False
        self._api('/sync/ratings/remove', method='POST',
                  body={'anime': [{'ids': dict(ids)}]})   # rating omitted
        return True

    def ratings(self, rating=None, type_: str = 'anime') -> List[dict]:
        """GET /sync/ratings/{type}[/{rating}]: the user's own 1-10 scores.

        `rating` is one value or a CSV like '9,10'; omit it for everything the
        user rated. Rows are /sync/all-items rows plus `user_rating`."""
        path = f'/sync/ratings/{type_}'
        if rating not in (None, ''):
            path += '/' + str(rating)
        d = self._api(path, {'language': 'en'})
        if isinstance(d, list):
            rows = d
        else:
            d = d if isinstance(d, dict) else {}
            rows = d.get(type_) or d.get('shows') or []
        return [r for r in rows if isinstance(r, dict)]

    def scrobble(self, action: str, ids: dict, episode, season=1,
                 progress=0) -> dict:
        """POST /scrobble/{start|pause|stop}: playback progress, in percent.

        Simkl marks the episode watched itself at >=80% on `stop` and keeps a
        resumable position below it, so one call covers both cases."""
        if action not in SCROBBLE:
            raise ValueError(f'unknown scrobble action {action!r}')
        if not ids:
            raise SimklError('simkl: no ids for scrobble call')
        try:
            pct = round(min(max(float(progress or 0), 0.0), 100.0), 2)
        except (TypeError, ValueError):
            raise ValueError(f'progress must be a number, got {progress!r}')
        body = {'progress': pct, 'anime': {'ids': dict(ids)},
                'episode': {'season': int(season), 'number': int(episode)}}
        try:
            return self._api(f'/scrobble/{action}', method='POST', body=body)
        except SimklError as ex:
            # 409 = that episode is already in history (rewatch, or our own
            # /sync/history mark a moment earlier). 400 RATE_LIMIT = Simkl's
            # 20s per-user write lock, i.e. a duplicate fire. Neither is worth
            # a scary log line; the next stop carries the newer position.
            if ex.status == 409 or ex.error == 'RATE_LIMIT':
                return {'skipped': ex.error or 'already watched'}
            raise

    def activities(self) -> dict:
        """GET /sync/activities: last-change stamp per list bucket.

        One cheap call answers "did anything move?" before a per-show pull."""
        d = self._api('/sync/activities')
        return d if isinstance(d, dict) else {}

    # --- cross-device resume --------------------------------------------
    def playback(self, show_ids=None) -> List[dict]:
        """GET /sync/playback/episodes: resume points saved by /scrobble/pause.

        `show_ids` is one ids dict or a list of them; None keeps every show.
        Rows: {id, simkl, mal, anilist, title, season, episode, progress
        (percent 0-100), paused_at}. `id` is what DELETE takes."""
        try:
            d = self._api('/sync/playback/episodes')
        except Exception:
            return []
        rows = d if isinstance(d, list) else _rows(d)
        want = _wanted(show_ids)
        out: List[dict] = []
        for it in rows:
            if not isinstance(it, dict):
                continue
            ep = it.get('episode') or {}
            show = it.get('show') or {}
            ids = show.get('ids') or {}
            if want and not any(str(ids.get(k)) in want
                                for k in ('simkl', 'mal', 'anilist')):
                continue
            out.append({'id': it.get('id'),
                        'simkl': ids.get('simkl'), 'mal': ids.get('mal'),
                        'anilist': ids.get('anilist'),
                        'title': show.get('title') or '',
                        'season': ep.get('season'), 'episode': ep.get('number'),
                        'progress': it.get('progress'),
                        'paused_at': it.get('paused_at')})
        return out

    def clear_playback(self, playback_id) -> bool:
        """DELETE /sync/playback/{id}: drop a resume point (204, no body).

        404 `empty` means it was already gone (Simkl marked the episode
        watched, or another device resumed it) - that is still a success."""
        try:
            self._api(f'/sync/playback/{int(playback_id)}', method='DELETE',
                      retries=0)
            return True
        except SimklError as ex:
            return ex.status == 404
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
        self._resume_rows: Optional[List[dict]] = None

    def enabled(self) -> bool:
        return self.acc.logged_in()

    def _match(self, title: str) -> Optional[dict]:
        if self._entries is None:
            self._entries = self.acc.library()
        import difflib
        import re

        def norm(s):
            return re.sub(r'[^a-z0-9 ]', ' ', (s or '').casefold()).strip()

        want = norm(title)
        if not want:
            return None
        best, score = None, 0.0
        for e in self._entries:
            got = norm(e['title'])
            r = difflib.SequenceMatcher(None, want, got).ratio()
            if want and (want in got or got in want):
                r = max(r, 0.85)              # substring is a strong signal
            if r > score:
                best, score = e, r
        return best if score >= 0.55 else None

    def _ids(self, title, mal=None, anilist=None) -> dict:
        """Ids for a playing title: the pinned ones, else the library match."""
        ids = {k: v for k, v in (('mal', mal), ('anilist', anilist)) if v}
        if ids:
            return ids
        e = self._match(title)
        return {k: e[k] for k in ('mal', 'anilist', 'simkl')
                if e and e.get(k)}

    def scrobble(self, title, num, progress, action='start', mal=None,
                 anilist=None):
        """Report playback progress. Returns Simkl's answer or None."""
        from . import log
        ids = self._ids(title, mal, anilist)
        if not ids:
            return None
        try:
            return self.acc.scrobble(action, ids, num, progress=progress)
        except Exception as ex:
            log.cprint(f'simkl: scrobble {action} failed for "{title}" ({ex})')
            return None

    def _playbacks(self) -> List[dict]:
        if self._resume_rows is None:
            self._resume_rows = self.acc.playback()
        return self._resume_rows

    def resume(self, title, num, mal=None, anilist=None) -> Optional[dict]:
        """A resume point Simkl saved for this episode on any device:
        {'percent': 42.2, 'id': 900} or None. One list call, cached."""
        want = _wanted(self._ids(title, mal, anilist))
        if not want:
            return None
        try:
            for r in self._playbacks():
                if r.get('episode') != num:
                    continue
                if any(str(r.get(k)) in want
                       for k in ('simkl', 'mal', 'anilist')):
                    return {'percent': float(r.get('progress') or 0),
                            'id': r.get('id')}
        except Exception:
            pass
        return None

    def forget(self, title, num, mal=None, anilist=None) -> bool:
        """Delete the Simkl resume point for an episode we finished here, so
        another device cannot offer a position behind our watch history."""
        from . import log
        r = self.resume(title, num, mal, anilist)
        if not r or not r.get('id'):
            return False
        ok = self.acc.clear_playback(r['id'])
        if ok:
            if self._resume_rows:
                self._resume_rows = [x for x in self._resume_rows
                                     if x.get('id') != r['id']]
            log.cprint(f'simkl: dropped resume point for ep{num}')
        return ok

    def mark_watched(self, title, num, ask=False, mal=None, anilist=None):
        from . import log
        ids = self._ids(title, mal, anilist)
        if not ids:
            log.cprint(f'simkl: no library match for "{title}" — not synced')
            return None
        label = f'mal {mal}' if mal else f'anilist {anilist}' if anilist \
            else title
        try:
            added = self.acc.mark_watched(ids, num)
        except Exception as ex:
            log.cprint(f'simkl: sync failed for {label} ({ex})')
            return None
        if added:
            log.cprint(f'simkl: marked ep {num} — {label}')
        else:
            log.cprint(f'simkl: ep {num} already watched — {label}')
        return added
