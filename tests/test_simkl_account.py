#!/usr/bin/env python3
"""test_simkl_account - Simkl device login, library parsing, progress push."""
import json
import os
import sys
import tempfile

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


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, url, headers=None, method='GET', data=None):
        self.calls.append((method, url, data))
        return {'url': url, 'method': method, 'data': data}

    def open(self, req, tries=None, timeout=None):
        for k, v in self.routes.items():
            if k in req['url']:
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
        '/sync/history': {'added': []},
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
        assert acc.mark_watched(a, 4) is True
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


def main():
    test_device_login_and_library()
    test_find_source()
    print('SIMKL_ACCOUNT OK')


if __name__ == '__main__':
    main()
