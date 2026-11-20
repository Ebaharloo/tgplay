"""tp.tracking.anilist_client - the ONE AniList GraphQL client.

AniList only (the metadata resolver already speaks AniList). Auth is the OAuth
"Auth Pin" flow: create an app, redirect = https://anilist.co/api/v2/oauth/pin,
then paste the token. Opt-in: no token = every call is a no-op.
"""
import difflib
import json
import os
import shutil
import subprocess
from typing import Optional

from ..config import Config
from ..http import HttpClient
import http.server
import urllib.parse
import urllib.request

# the LATEST authorize_browser call owns this: any alive callback server
# (even one orphaned by a canceled dialog) delivers the redirect to it
_AUTH_WAIT = {'done': None, 'result': None}


class Callback(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/t?'):
            q = urllib.parse.parse_qs(self.path[3:])
            tok = (q.get('access_token') or [''])[0]
            res = _AUTH_WAIT.get('result')      # {} is falsy - never use
            if res is None:                     # `or {}` here, it discards
                res = {}                        # the write
            if tok:
                res['token'] = tok
            body = (b'<meta charset="utf-8">'
                    b'<body style="background:#111;color:#ddd;'
                    b'font-family:sans-serif;text-align:center;'
                    b'padding-top:40px"><h2>&#10003; AniList '
                    b'connected - you can close this tab.</h2></body>')
        elif self.path.startswith('/?code='):
            q = urllib.parse.parse_qs(self.path[2:])
            code = (q.get('code') or [''])[0]
            res = _AUTH_WAIT.get('result')
            if res is None:
                res = {}
            if code:
                res['code'] = code
                ev = _AUTH_WAIT.get('done')
                if ev is not None:
                    ev.set()                # deliver to the CURRENT waiter
            body = (b'<meta charset="utf-8">'
                    b'<body style="background:#111;color:#ddd;'
                    b'font-family:sans-serif;text-align:center;'
                    b'padding-top:40px"><h2>&#10003; AniList '
                    b'authorized - one moment&hellip;</h2></body>')
        else:
            body = (b'<meta charset="utf-8">'
                    b'<script>if(location.hash.length>1)'
                    b'fetch("/t?"+location.hash.slice(1));</script>'
                    b'<body style="background:#111;color:#ddd;'
                    b'font-family:sans-serif;text-align:center;'
                    b'padding-top:40px"><h2>Authorizing&hellip;</h2>'
                    b'</body>')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

API = 'https://graphql.anilist.co'
_SEARCH = ('query($s:String){Page(page:1,perPage:8){media(search:$s,type:ANIME){'
           'id idMal title{romaji english native} synonyms}}}')


def _read(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def _write(path, d):
    from ..config import save_json
    save_json(path, d)


class Tracker:
    def __init__(self, config: Optional[Config] = None,
                 http: Optional[HttpClient] = None):
        self.cfg = config or Config()
        self.http = http or HttpClient(timeout=20)

    # --- auth --------------------------------------------------------------
    def _auth(self) -> dict:
        return _read(self.cfg.anilist_auth, {})

    def token(self) -> Optional[str]:
        return os.environ.get('AGP_ANILIST_TOKEN') or self._auth().get('token')

    def enabled(self) -> bool:
        if os.environ.get('AGP_NO_TRACK'):
            return False
        if os.environ.get('AGP_ANILIST_TOKEN'):
            return True
        a = self._auth()
        return bool(a.get('token')) and a.get('enabled', True)

    # --- graphql -----------------------------------------------------------
    def _gql(self, query, variables=None, token=None):
        h = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if token:
            h['Authorization'] = 'Bearer ' + token
        req = self.http.request(API, method='POST', headers=h,
                                data=json.dumps({'query': query,
                                                 'variables': variables or {}}
                                                ).encode())
        r = self.http.open(req)
        try:
            d = json.load(r)
        finally:
            from ..http import _quiet_close
            _quiet_close(r)
        if d.get('errors'):
            raise RuntimeError(d['errors'][0].get('message', 'graphql error'))
        return d

    def viewer(self, token=None):
        return self._gql('query{Viewer{id name}}',
                         token=token or self.token())['data']['Viewer']

    def save_progress(self, media_id, watched, total=None, token=None):
        status = 'COMPLETED' if (total and watched >= total) else 'CURRENT'
        q = ('mutation($id:Int,$p:Int,$s:MediaListStatus){'
             'SaveMediaListEntry(mediaId:$id,progress:$p,status:$s)'
             '{progress status}}')
        return self._gql(q, {'id': media_id, 'p': int(watched), 's': status},
                         token=token)['data']['SaveMediaListEntry']

    def media(self, mid):
        q = ('query($id:Int){Media(id:$id){id episodes title{romaji english} '
             'mediaListEntry{progress} '
             'nextAiringEpisode{episode airingAt timeUntilAiring}}}')
        return self._gql(q, {'id': mid})['data']['Media']

    # --- title -> media id -------------------------------------------------
    def resolve_media(self, title, ask=True):
        cache = _read(self.cfg.anilist_ids, {})
        for k, v in cache.items():
            if k.casefold() == title.casefold():
                return v['id'] if isinstance(v, dict) else v
        try:
            media = self._gql(_SEARCH, {'s': title})['data']['Page']['media']
        except Exception:
            return None
        scored = []
        for m in media:
            names = [x for x in m['title'].values() if x]
            names += [s for s in (m.get('synonyms') or []) if s]
            best = max(difflib.SequenceMatcher(
                None, title.casefold(), n.casefold()).ratio() for n in names)
            scored.append((best, m))
        scored.sort(key=lambda kv: kv[0], reverse=True)
        if not scored:
            return None
        top = scored[0]
        if top[0] >= 0.85 or (len(scored) == 1 and top[0] >= 0.6):
            cache[title] = {'id': top[1]['id'],
                            'episodes': top[1].get('episodes')}
            _write(self.cfg.anilist_ids, cache)
            return top[1]['id']
        if ask and not os.environ.get('AGP_NOPICK'):
            print(f'track: ambiguous for "{title}"')
        return None

    # --- progress ----------------------------------------------------------
    _STATUS = {'CURRENT': 'watching', 'PLANNING': 'plantowatch',
               'PAUSED': 'hold', 'DROPPED': 'dropped',
               'COMPLETED': 'completed', 'REPEATING': 'watching'}

    def library(self, statuses=None):
        """The user's AniList lists, in the SAME row shape Simkl rows use,
        so library.overview() can merge them by title."""
        uid = (self.viewer(self.token()) or {}).get('id')
        # AniList quirk: the userId must be a literal in the query text
        # (the variable form answers 'User ID/Name & Type arguments required')
        q = (f'query{{MediaListCollection(userId:{int(uid)},type:ANIME){{'
             'lists{entries{status progress updatedAt '
             'media{id idMal episodes title{romaji english} '
             'coverImage{large}}}}}}')
        d = self._gql(q, token=self.token())
        ml = (d.get('data') or {}).get('MediaListCollection') or {}
        lists = ml.get('lists') or []
        out = []
        for lst in lists:
            for e in lst.get('entries') or []:
                m = e.get('media') or {}
                t = m.get('title') or {}
                title = t.get('english') or t.get('romaji') or ''
                prog = e.get('progress') or 0
                ts = e.get('updatedAt')
                lw = ''
                if ts:
                    try:
                        from datetime import datetime
                        lw = datetime.fromtimestamp(int(ts)).strftime(
                            '%Y-%m-%d %H:%M')
                    except Exception:
                        lw = ''
                row = {
                    'title': title, 'simkl': None,
                    'mal': m.get('idMal'), 'anilist': m.get('id'),
                    'status': self._STATUS.get(e.get('status'),
                                               e.get('status', '') or ''),
                    'watched': prog, 'total': m.get('episodes') or 0,
                    'next_ep': (prog + 1) if prog else None,
                    'air_date': None, 'last_watched': lw,
                    'poster': (m.get('coverImage') or {}).get('large'),
                }
                if statuses:
                    row = row if row['status'] in statuses else None
                if row and title:
                    out.append(row)
        return out

    @staticmethod
    def watched_of(entry) -> int:
        """progress.json `ep` is current-or-next -> fully watched = ep - 1."""
        try:
            return max(0, int(entry.get('ep', 0)) - 1)
        except Exception:
            return 0

    def _progress(self) -> dict:
        return _read(self.cfg.progress, {})

    def new_episodes(self, progress=None, ask=False):
        out = []
        prog = progress if isinstance(progress, dict) else self._progress()
        for title, e in prog.items():
            mid = self.resolve_media(title, ask=ask)
            if not mid:
                continue
            try:
                m = self.media(mid)
            except Exception:
                continue
            watched = max(self.watched_of(e),
                          (m.get('mediaListEntry') or {}).get('progress') or 0)
            nae = m.get('nextAiringEpisode')
            aired = (nae['episode'] - 1) if nae else (m.get('episodes') or 0)
            if aired and watched < aired:
                out.append({'title': title, 'media_id': mid, 'aired': aired,
                            'watched': watched, 'new': aired - watched,
                            'next_airing': nae})
        return out

    def mark_watched(self, title, watched, ask=False, mal=None, anilist=None):
        mid = anilist or self.resolve_media(title, ask=ask)
        if not mid:
            return None
        m = self.media(mid)
        cur = (m.get('mediaListEntry') or {}).get('progress') or 0
        if watched <= cur:
            return None
        return self.save_progress(mid, watched, m.get('episodes'))

    def notify_new(self, progress=None):
        rows = self.new_episodes(progress)
        for r in rows:
            msg = (f"{r['title']}: {r['new']} new episode(s) "
                   f"(watched {r['watched']}/{r['aired']})")
            print(f'track: {msg}')
            self._desktop('agp · new episode', msg)
        return rows

    def sync(self, dry=False, progress=None):
        if not self.enabled() and not self.token():
            print('track: not logged in (run: agp login <CLIENT_ID>)')
            return []
        done = []
        prog = progress if isinstance(progress, dict) else self._progress()
        for title, e in prog.items():
            w = self.watched_of(e)
            if w <= 0:
                continue
            mid = self.resolve_media(title, ask=False)
            if not mid:
                continue
            if dry:
                print(f'  would set {title} -> ep {w} (AniList {mid})')
                done.append((title, mid, w))
                continue
            try:
                m = self.media(mid)
                total = m.get('episodes')
                cur = (m.get('mediaListEntry') or {}).get('progress') or 0
                if w <= cur:
                    print(f'  {title}: already at {cur} (local {w})')
                    continue
                res = self.save_progress(mid, w, total)
                print(f"  {title}: {res['progress']} eps ({res['status']})")
                done.append((title, mid, w))
            except Exception as ex:
                print(f'  {title}: sync failed ({ex})')
        if not done:
            print('track: nothing to sync')
        return done

    @staticmethod
    def _desktop(summary, body):
        if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            return
        if not shutil.which('notify-send'):
            return
        try:
            subprocess.run(['notify-send', '-a', 'agp', summary, body],
                           timeout=5)
        except Exception:
            pass

    # --- login / status ----------------------------------------------------
    def login(self, client_id=None, tok=None, open_browser=True):
        a = self._auth()
        cid = (client_id or os.environ.get('AGP_ANILIST_CLIENT_ID')
               or a.get('client_id'))
        if not tok:
            if not cid:
                print('tracking: create an AniList app first:')
                print('  1) https://anilist.co/settings/developer')
                print('  2) Redirect URL: https://anilist.co/api/v2/oauth/pin')
                try:
                    cid = input('client id: ').strip()
                except EOFError:
                    return None
            url = ('https://anilist.co/api/v2/oauth/authorize?client_id='
                   f'{cid}&response_type=token')
            print(f'tracking: open, approve, copy the token:\n  {url}')
            if open_browser:
                try:
                    import webbrowser
                    webbrowser.open(url)
                except Exception:
                    pass
            try:
                tok = input('token: ').strip()
            except EOFError:
                return None
        if not tok:
            print('tracking: no token, aborted')
            return None
        try:
            u = self.viewer(tok)
        except Exception as ex:
            print(f'tracking: token rejected ({ex})')
            return None
        a.update({'client_id': cid or a.get('client_id'), 'token': tok,
                  'user': u, 'enabled': True})
        a.setdefault('auto_sync', True)
        a.setdefault('notify', True)
        _write(self.cfg.anilist_auth, a)
        print(f"tracking: logged in as {u['name']}")
        return u

    def _exchange(self, client_id, client_secret, code, redirect_uri):
        """authorization_code -> access token (AniList needs the secret)."""
        import urllib.parse
        body = urllib.parse.urlencode({
            'grant_type': 'authorization_code', 'client_id': client_id,
            'client_secret': client_secret or '', 'redirect_uri': redirect_uri,
            'code': code}).encode()
        req = self.http.request('https://anilist.co/api/v2/oauth/token',
                                method='POST', headers={
                                    'Content-Type':
                                        'application/x-www-form-urlencoded'},
                                data=body)
        r = self.http.open(req, timeout=20)
        try:
            d = json.load(r)
        finally:
            r.close()
        if not d.get('access_token'):
            raise RuntimeError(f'anilist token exchange failed: {d}')
        return d['access_token']

    def authorize_browser(self, client_id, client_secret=None, port=8642,
                          timeout=300):
        """Real OAuth: open the AniList authorize page, catch the redirect on
        a localhost callback, exchange nothing (implicit), save the token.

        Requires the AniList app's Redirect URL to be
        http://localhost:<port>/ - the one-time setup dialog says exactly that.
        Returns the user dict, or None on timeout."""
        import http.server
        import threading
        import urllib.parse
        import webbrowser
        result = {}
        done = threading.Event()
        _AUTH_WAIT['done'] = done
        _AUTH_WAIT['result'] = result

        srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), Callback)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            # send EXACTLY the redirect the user registered - AniList
            # compares the strings, and 'http://localhost:8642' without the
            # trailing slash was the mismatch (user report 2026-11-20)
            redir = f'http://localhost:{port}'
            # AniList ONLY supports the authorization-code grant:
            # response_type=token answers 'unsupported_grant_type'.
            url = ('https://anilist.co/api/v2/oauth/authorize?client_id='
                   f'{client_id}&response_type=code&redirect_uri='
                   + urllib.parse.quote(redir, safe=''))
            webbrowser.open(url)
            if not done.wait(timeout):
                return None
            code = _AUTH_WAIT['result']['code']
            tok = self._exchange(client_id, client_secret, code, redir)
            user = self.viewer(tok)
            a = self._auth()
            a.update({'client_id': client_id, 'token': tok,
                      'user': user, 'enabled': True})
            a.setdefault('auto_sync', True)
            from ..config import save_json
            save_json(self.cfg.anilist_auth, a)
            return user
        finally:
            srv.shutdown()

    def logout(self):
        try:
            os.remove(self.cfg.anilist_auth)
            print('tracking: logged out')
        except OSError:
            print('tracking: not logged in')

    def status(self):
        a = self._auth()
        if not a.get('token'):
            print('tracking: not logged in (run: agp login <CLIENT_ID>)')
            return
        try:
            u = self.viewer()
        except Exception as ex:
            print(f'tracking: token invalid ({ex}) - run: agp login')
            return
        print(f"tracking: {u['name']} "
              f"(auto_sync={a.get('auto_sync', True)}, "
              f"notify={a.get('notify', True)})")
        rows = self.new_episodes()
        for r in rows:
            print(f"  {r['title']}: {r['watched']}/{r['aired']} (+{r['new']} new)")
        if not rows:
            print('  all caught up')

    def cli(self, cmd, args):
        if cmd == 'login':
            cid = next((x for x in args if not x.startswith('-')), None)
            return self.login(cid)
        if cmd == 'logout':
            return self.logout()
        if cmd == 'sync':
            return self.sync(dry='--dry' in args)
        if cmd in ('new', 'notify'):
            rows = self.notify_new()
            if not rows:
                print('track: nothing new')
            return rows
        return self.status()


# Simkl list status -> AniList MediaListStatus (the map that was missing)
STATUS_MAP = {'watching': 'CURRENT', 'plantowatch': 'PLANNING',
              'completed': 'COMPLETED', 'hold': 'PAUSED',
              'dropped': 'DROPPED'}


def gql(query, variables=None, token=None, http=None, timeout=20):
    """POST one GraphQL query; raises RuntimeError on a GraphQL error."""
    h = {'Content-Type': 'application/json', 'Accept': 'application/json',
         'User-Agent': 'tgplay/1.0'}
    if token:
        h['Authorization'] = 'Bearer ' + token
    body = json.dumps({'query': query, 'variables': variables or {}}).encode()
    if http is None:
        with urllib.request.urlopen(
                urllib.request.Request(ANILIST_GQL, data=body, headers=h),
                timeout=timeout) as r:
            d = json.load(r)
    else:
        r = http.open(http.request(ANILIST_GQL, method='POST', headers=h,
                                   data=body))
        try:
            d = json.load(r)
        finally:
            _quiet_close(r)
    if d.get('errors'):
        raise RuntimeError(d['errors'][0].get('message', 'graphql error'))
    return d.get('data') or {}


class AniListClient(Tracker):
    def __init__(self, cfg, http: Optional[HttpClient] = None):
        super().__init__(cfg, http)

    def save_progress(self, media_id, watched, total=None, token=None,
                      status=None):
        """One SaveMediaListEntry: progress + the mapped list status.

        `status` is a Simkl status name or an AniList one; None derives
        CURRENT/COMPLETED from the episode count (the old behaviour).
        """
        st = (status if status in STATUS_MAP.values()
              else STATUS_MAP.get(status or '')
              or ('COMPLETED' if (total and watched >= total) else 'CURRENT'))
        q = ('mutation($id:Int,$p:Int,$s:MediaListStatus){'
             'SaveMediaListEntry(mediaId:$id,progress:$p,status:$s)'
             '{progress status}}')
        return self._gql(q, {'id': int(media_id), 'p': int(watched), 's': st},
                         token=token)['data']['SaveMediaListEntry']

    def set_status(self, media_id, status, progress=None, token=None):
        st = STATUS_MAP.get(status, status)
        q = ('mutation($id:Int,$s:MediaListStatus,$p:Int){'
             'SaveMediaListEntry(mediaId:$id,status:$s,progress:$p)'
             '{progress status}}')
        return self._gql(q, {'id': int(media_id), 's': st,
                             'p': None if progress is None else int(progress)},
                         token=token)['data']['SaveMediaListEntry']
