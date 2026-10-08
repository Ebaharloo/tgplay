"""tp.tracking - AniList progress sync + new-episode notifications.

AniList only (the metadata resolver already speaks AniList). Auth is the OAuth
"Auth Pin" flow: create an app, redirect = https://anilist.co/api/v2/oauth/pin,
then paste the token. Opt-in: no token = every call is a no-op.
"""
import difflib
import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional

from .config import Config
from .http import HttpClient

API = 'https://graphql.anilist.co'
_SEARCH = ('query($s:String){Page(page:1,perPage:8){media(search:$s,type:ANIME){'
           'id idMal title{romaji english native} synonyms}}}')


def _read(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def _write(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(d, open(path, 'w'))


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
            from .http import _quiet_close
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

    def mark_watched(self, title, watched, ask=False):
        mid = self.resolve_media(title, ask=ask)
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
