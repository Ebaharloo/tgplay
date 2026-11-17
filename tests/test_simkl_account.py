#!/usr/bin/env python3
"""test_simkl_account - Simkl device login, library parsing, watched sync.

All HTTP is mocked: no live Simkl calls.
"""
import email.message
import io
import json
import os
import sys
import tempfile
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tp import simkl_account  # noqa: E402
from tp import library as lib  # noqa: E402


class Resp:
    def __init__(self, d):
        self._d = d

    def read(self, n=-1):
        return self._d

    def close(self):
        pass


class Err:
    """A route that answers with an HTTP error instead of JSON."""

    def __init__(self, code, body=None, headers=None):
        self.code, self.body, self.headers = code, body or {}, headers or {}


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, url, headers=None, method='GET', data=None):
        self.calls.append((method, url, data, headers or {}))
        return {'url': url, 'method': method, 'data': data,
                'headers': headers or {}}

    def open(self, req, tries=None, timeout=None):
        for k, v in self.routes.items():
            if k in req['url']:
                if isinstance(v, list):       # first answer, then the next
                    v = v.pop(0) if len(v) > 1 else v[0]
                if isinstance(v, Err):
                    h = email.message.Message()
                    for n, x in v.headers.items():
                        h[n] = x
                    raise urllib.error.HTTPError(
                        req['url'], v.code, 'error', h,
                        io.BytesIO(json.dumps(v.body).encode()))
                return Resp(json.dumps(v).encode())
        return Resp(b'{}')


class Cfg:
    def __init__(self, d):
        self._d = d

    @property
    def simkl_auth(self):
        return os.path.join(self._d, 'simkl_auth.json')

    @property
    def progress(self):
        return os.path.join(self._d, 'progress.json')


WATCHING = {'watching': [
    {'show': {'title': 'Show A', 'ids': {'mal': 1, 'simkl': 10}},
     'status': 'watching', 'watched_episodes_count': 3,
     'total_episodes_count': 12, 'next_to_watch_info': {'episode': 4}},
    {'show': {'title': 'Caught Up', 'ids': {'mal': 2, 'simkl': 20}},
     'status': 'watching', 'watched_episodes_count': 12,
     'total_episodes_count': 12},
], 'plantowatch': [
    {'show': {'title': 'Later', 'ids': {'mal': 3, 'simkl': 30}},
     'status': 'plantowatch', 'watched_episodes_count': 0,
     'total_episodes_count': 6},
]}


def test_device_login_and_library():
    d = tempfile.mkdtemp()
    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    routes = {
        '/oauth2/device': {'device_code': 'dc', 'user_code': 'AB-CD',
                           'verification_uri_complete': 'https://simkl.com/pin',
                           'interval': 0, 'expires_in': 900},
        '/oauth2/token': {'access_token': 'simkl_at_x',
                          'refresh_token': 'simkl_rt_y',
                          'scope': 'media:read media:write'},
        '/users/settings': {'user': {'name': 'tester'}},
        '/sync/all-items': WATCHING,
        '/sync/history': {'added': {'episodes': 1}},
    }
    http = FakeHttp(routes)
    acc = simkl_account.SimklAccount(Cfg(d), http)
    try:
        assert acc.login() is not None
        assert acc.logged_in(), 'should be logged in'
        rows = acc.library()
        titles = [r['title'] for r in rows]
        assert 'Show A' in titles and 'Later' in titles, titles
        a = next(r for r in rows if r['title'] == 'Show A')
        assert (a['mal'], a['simkl'], a['watched'], a['total'], a['next_ep']) \
            == (1, 10, 3, 12, 4), a
        up = acc.up_next()
        assert [u['title'] for u in up] == ['Show A'], up   # Caught Up excluded
        assert acc.mark_watched(a, 4) == 1
        post = [c for c in http.calls if c[0] == 'POST'
                and '/sync/history' in c[1]]
        body = json.loads(post[-1][2])
        assert body['anime'][0]['ids']['mal'] == 1
        assert body['anime'][0]['seasons'][0]['episodes'][0]['number'] == 4
    finally:
        os.environ.pop('AGP_SIMKL_CLIENT_ID', None)
    print('PASS simkl device login + library + progress push')


def test_find_source():
    old = None
    import tp.search as searchmod
    old = searchmod.search_all
    searchmod.search_all = lambda q, **k: [
        {'title': 'Other Show', 'url': 'agp:other', 'source': 'agp'},
        {'title': 'Show A', 'url': 'axp:show-a', 'source': 'axp'}]
    try:
        assert lib.find_source('Show A') == ('axp', 'axp:show-a')
        assert lib.find_source('') is None
    finally:
        searchmod.search_all = old
    print('PASS library find_source')


def test_pin_flow_failures():
    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    sleep = simkl_account.time.sleep
    simkl_account.time.sleep = lambda s: None
    try:
        # device endpoint refuses the client
        http = FakeHttp({'/oauth2/device': Err(401, {'error': 'invalid_client'})})
        acc = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http)
        assert acc.start_device() is None
        assert acc.login() is None

        # user never approves: the poll ends with expired_token
        http = FakeHttp({
            '/oauth2/device': {'device_code': 'dc', 'user_code': 'AB-CD',
                               'verification_uri_complete': 'https://simkl.com/pin',
                               'interval': 0, 'expires_in': 900},
            '/oauth2/token': {'error': 'expired_token'}})
        acc = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http)
        assert acc.login() is None
        assert not acc.logged_in()
    finally:
        simkl_account.time.sleep = sleep
        os.environ.pop('AGP_SIMKL_CLIENT_ID', None)
    print('PASS simkl PIN flow failures')


def test_token_refresh():
    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    try:
        d = tempfile.mkdtemp()
        acc = simkl_account.SimklAccount(Cfg(d), FakeHttp({}))
        # 1. expired-at-login: refreshed BEFORE the call, no 401 needed
        acc._save(access_token='old', refresh_token='rt', expires_at=1)
        http = FakeHttp({'/oauth2/token': {'access_token': 'fresh',
                                           'expires_in': 604800},
                         '/sync/all-items': WATCHING})
        acc.http = http
        acc.library()
        gets = [c for c in http.calls if '/sync/all-items' in c[1]]
        assert gets[-1][3]['Authorization'] == 'Bearer fresh', gets[-1][3]
        assert acc._auth()['refresh_token'] == 'rt'      # kept when not rotated
        assert acc._auth()['expires_at'] > 1_700_000_000

        # 2. server says 401 (token revoked/expired early): refresh once, retry
        acc2 = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), None)
        acc2._save(access_token='stale', refresh_token='rt2')
        http2 = FakeHttp({'/sync/all-items': [Err(401, {'error': 'invalid_token'}),
                                              WATCHING],
                          '/oauth2/token': {'access_token': 'fresh2'}})
        acc2.http = http2
        assert acc2.library()
        auth = [c[3].get('Authorization') for c in http2.calls
                if '/sync/all-items' in c[1]]
        assert auth == ['Bearer stale', 'Bearer fresh2'], auth
    finally:
        os.environ.pop('AGP_SIMKL_CLIENT_ID', None)
    print('PASS simkl token refresh (expiry + 401)')


def test_history_payloads():
    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    try:
        http = FakeHttp({'/sync/history': {'added': {'episodes': 1}}})
        acc = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http)
        ids = {'mal': 1, 'simkl': 10}
        acc.mark_episode_watched(ids, 2, 5)
        acc.unmark_episode_watched(ids, 2, 5)
        acc.mark_season_watched(ids, 2)
        acc.unmark_season_watched(ids, 2)
        acc.mark_show_complete(ids)
        acc.unmark_show_complete(ids)

        posts = [c for c in http.calls if c[0] == 'POST']
        assert len(posts) == 6, posts
        assert all(c[3]['simkl-api-key'] == 'cid' for c in posts)
        assert all(c[3]['User-Agent'].startswith('tgplay/') for c in posts)
        bodies = [json.loads(c[2]) for c in posts]

        ep = bodies[0]['anime'][0]
        assert ep['ids'] == ids
        assert ep['seasons'] == [{'number': 2, 'episodes': [{'number': 5}]}]
        assert '/sync/history?' in posts[0][1]
        assert '/sync/history/remove?' in posts[1][1]
        assert posts[0][1].count('/remove') == 0

        season = bodies[2]['anime'][0]['seasons'][0]
        assert season == {'number': 2}, season
        assert 'seasons' not in bodies[4]['anime'][0], bodies[4]
        assert 'seasons' not in bodies[5]['anime'][0]
        assert [b['anime'][0]['ids'] for b in bodies] == [ids] * 6
    finally:
        os.environ.pop('AGP_SIMKL_CLIENT_ID', None)
    print('PASS simkl mark/unmark payload shapes')


def test_get_watched():
    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    try:
        rows = {'watching': [
            {'show': {'ids': {'mal': 1, 'simkl': 10}},
             'status': 'watching', 'watched_episodes_count': 1,
             'seasons': [{'number': 1, 'episodes': [{'number': 1}]}]},
            {'show': {'ids': {'mal': 99, 'simkl': 90}},
             'status': 'watching', 'watched_episodes_count': 0}]}
        http = FakeHttp({'/sync/all-items/anime': rows})
        acc = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http)
        got = acc.get_watched({'mal': 1})
        assert [r['show']['ids']['simkl'] for r in got] == [10], got
        assert got[0]['seasons'][0]['episodes'][0]['number'] == 1
        assert len(acc.get_watched()) == 2
        assert acc.get_watched([{'simkl': 90}])[0]['show']['ids']['mal'] == 99
        call = [c for c in http.calls if '/sync/all-items' in c[1]][0]
        assert 'extended=full' in call[1]
    finally:
        os.environ.pop('AGP_SIMKL_CLIENT_ID', None)
    print('PASS simkl get_watched')


def test_429_retry():
    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    sleep = simkl_account.time.sleep
    simkl_account.time.sleep = lambda s: None
    try:
        # per-second 429: retried once, payload preserved
        http = FakeHttp({'/sync/history': [
            Err(429, {'error': 'rate_limit'}, {'Retry-After': '45000'}),
            {'added': {'episodes': 1}}]})
        acc = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http)
        d = acc.mark_episode_watched({'mal': 1}, 1, 1)
        assert d['added']['episodes'] == 1
        posts = [c for c in http.calls if c[0] == 'POST']
        assert len(posts) == 2, posts
        assert posts[0][2] == posts[1][2]          # same body on the retry

        # daily quota: Retry-After past the cap is reported, not slept off
        http2 = FakeHttp({'/sync/history': Err(
            429, {'error': 'user_limit_exceeded'}, {'Retry-After': '4000'})})
        acc2 = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http2)
        try:
            acc2.mark_episode_watched({'mal': 1}, 1, 1)
            raise AssertionError('daily 429 must raise')
        except simkl_account.SimklError as ex:
            assert (ex.status, ex.error) == (429, 'user_limit_exceeded'), ex
        assert len(http2.calls) == 1

        # 5xx is retried with backoff, then reported as a typed error
        http3 = FakeHttp({'/sync/history': Err(503, {'error': 'internal'})})
        acc3 = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http3)
        try:
            acc3.mark_episode_watched({'mal': 1}, 1, 1)
            raise AssertionError('503 must raise once retries run out')
        except simkl_account.SimklError as ex:
            assert ex.status == 503
        assert len(http3.calls) == simkl_account.RETRIES + 1
    finally:
        simkl_account.time.sleep = sleep
        os.environ.pop('AGP_SIMKL_CLIENT_ID', None)
    print('PASS simkl 429 / 5xx retry')


def test_scrobble_ratings_status():
    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    try:
        http = FakeHttp({'/scrobble/': {'action': 'scrobble'},
                         '/sync/ratings': {}, '/sync/add-to-list': {},
                         '/sync/activities': {'all': '2026-11-17T00:00:00Z',
                                              'anime': {'all': 'x'}}})
        acc = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http)
        acc._save(access_token='at', refresh_token='rt')
        ids = {'mal': 1, 'simkl': 10}
        acc.scrobble('start', ids, 3)
        acc.scrobble('stop', ids, 3, progress=63.456)
        acc.scrobble('pause', ids, 3, progress=150)
        posts = [c for c in http.calls if c[0] == 'POST']
        assert '/scrobble/start?' in posts[0][1]
        assert '/scrobble/stop?' in posts[1][1]
        b = [json.loads(c[2]) for c in posts[:3]]
        assert b[0] == {'progress': 0.0, 'anime': {'ids': ids},
                        'episode': {'season': 1, 'number': 3}}, b[0]
        assert (b[1]['progress'], b[2]['progress']) == (63.46, 100.0), b
        for bad, exc in ((('bogus', ids, 1), ValueError),
                         (('start', {}, 1), simkl_account.SimklError),
                         (('start', ids, 1, 1, 'abc'), ValueError)):
            try:
                acc.scrobble(*bad)
                raise AssertionError(f'{bad} must raise')
            except exc:
                pass

        assert acc.rate(ids, 8) is True
        rated = [c for c in http.calls if '/sync/ratings' in c[1]][-1]
        assert json.loads(rated[2]) == {'anime': [{'ids': ids, 'rating': 8}]}
        for bad in (0, 11):                 # Simkl would drop it silently
            try:
                acc.rate(ids, bad)
                raise AssertionError('out-of-range rating must raise')
            except ValueError:
                pass
        assert acc.add_to_list(ids, 'dropped') is True
        try:
            acc.add_to_list(ids, 'plan')
            raise AssertionError('unknown list status must raise')
        except ValueError:
            pass
        assert acc.activities()['anime'] == {'all': 'x'}

        # 409 on stop = episode already in history: no error, nothing to log
        http2 = FakeHttp({'/scrobble/stop': Err(409, {'error': 'conflict'})})
        acc2 = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http2)
        acc2._save(access_token='at', refresh_token='rt')
        assert acc2.scrobble('stop', ids, 3, progress=95) == {
            'skipped': 'conflict'}

        # 400 RATE_LIMIT = the 20s per-user write lock, not a broken request
        http3 = FakeHttp({'/scrobble/stop': Err(400, {'error': 'RATE_LIMIT'})})
        acc3 = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http3)
        acc3._save(access_token='at', refresh_token='rt')
        assert acc3.scrobble('stop', ids, 3, progress=5)['skipped'] == \
            'RATE_LIMIT'
    finally:
        os.environ.pop('AGP_SIMKL_CLIENT_ID', None)
    print('PASS simkl scrobble / ratings / list status / activities')


def test_playlist_reports_progress():
    import time
    from tp.playlist import Playlist
    from tp.tracking import MultiTracker

    class Tr:
        def __init__(self):
            self.calls = []

        def enabled(self):
            return True

        def scrobble(self, *a, **k):
            self.calls.append((a, k))
            return {'action': 'scrobble'}

    class Show:
        title = 'Show A'
        mal_id = 21
        anilist_id = None

    pl = object.__new__(Playlist)      # no mpv/network: just the hook + worker
    tr = Tr()
    pl.tracker = MultiTracker([tr])
    pl.mal_id = None
    pl.provider = Show()
    pl._scrobble('start', 3, 0)
    pl._scrobble('stop', 3, 42.5)
    deadline = time.time() + 5
    while len(tr.calls) < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert tr.calls == [
        (('Show A', 3, 0), {'action': 'start', 'mal': 21, 'anilist': None}),
        (('Show A', 3, 42.5), {'action': 'stop', 'mal': 21,
                               'anilist': None})], tr.calls
    print('PASS playlist scrobble hook (start/stop)')


def test_logout_revokes_then_deletes():
    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    try:
        d = tempfile.mkdtemp()
        http = FakeHttp({'/oauth2/revoke': {}})
        acc = simkl_account.SimklAccount(Cfg(d), http)
        acc._save(access_token='at', refresh_token='rt')
        acc.logout()
        rev = [c for c in http.calls if '/oauth2/revoke' in c[1]]
        assert rev, http.calls
        assert b'token=rt' in rev[-1][2], rev[-1][2]
        assert b'client_id=cid' in rev[-1][2], rev[-1][2]
        assert not os.path.exists(acc.cfg.simkl_auth)

        # revoke refused (401 invalid_client): local token still goes away
        http2 = FakeHttp({'/oauth2/revoke': Err(401,
                                               {'error': 'invalid_client'})})
        acc2 = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http2)
        acc2._save(access_token='at', refresh_token='rt')
        acc2.logout()
        assert not os.path.exists(acc2.cfg.simkl_auth)

        # nothing saved: no revoke call at all
        http3 = FakeHttp({})
        acc3 = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http3)
        acc3.logout()
        assert not [c for c in http3.calls if '/oauth2/revoke' in c[1]]
    finally:
        os.environ.pop('AGP_SIMKL_CLIENT_ID', None)
    print('PASS logout revokes the token before deleting it')


def test_stats_uses_account_id():
    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    try:
        http = FakeHttp({
            '/users/settings': {'account': {'id': 77}, 'user': {'name': 't'}},
            '/users/77/stats': {'total_mins': 600,
                                'anime': {'completed': {'count': 4}},
                                'watched_last_week': {'total_mins': 30}}})
        acc = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http)
        acc._save(access_token='at')
        s = acc.stats()
        assert s['total_mins'] == 600, s
        assert any('/users/77/stats' in c[1] for c in http.calls), http.calls

        # explicit id: no /users/settings round-trip
        http2 = FakeHttp({'/users/9/stats': {'total_mins': 1}})
        acc2 = simkl_account.SimklAccount(Cfg(tempfile.mkdtemp()), http2)
        acc2._save(access_token='at')
        assert acc2.stats(9)['total_mins'] == 1
        assert not [c for c in http2.calls if '/users/settings' in c[1]]
    finally:
        os.environ.pop('AGP_SIMKL_CLIENT_ID', None)
    print('PASS stats resolves the account id once')


def main():
    test_device_login_and_library()
    test_pin_flow_failures()
    test_token_refresh()
    test_history_payloads()
    test_get_watched()
    test_429_retry()
    test_scrobble_ratings_status()
    test_playlist_reports_progress()
    test_logout_revokes_then_deletes()
    test_stats_uses_account_id()
    test_find_source()
    print('SIMKL_ACCOUNT OK')


if __name__ == '__main__':
    main()
