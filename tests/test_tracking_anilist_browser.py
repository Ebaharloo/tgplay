#!/usr/bin/env python3
"""test_tracking_anilist_browser - the localhost OAuth callback.

The authorize page redirects to http://localhost:<port>/#access_token=...
(the fragment never reaches a server), so the served page's JS posts the
fragment back to /t. This test drives that loop for real, without a browser.
"""
import os
import sys
import threading
import time
import types
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.tracking.anilist_client import Tracker             # noqa: E402


def _tracker(tmp, monkeypatch):
    tr = object.__new__(Tracker)
    tr.cfg = types.SimpleNamespace(anilist_auth=f'{tmp}/anilist_auth.json')
    monkeypatch.setattr(Tracker, 'viewer',
                        lambda self, tok, *a, **k: {'name': 'tester'})
    return tr


def test_callback_catches_the_code_and_exchanges_it(tmp_path, monkeypatch):
    """AniList only supports the authorization-code grant (response_type=
    token answers unsupported_grant_type - user screenshot 2026-11-20)."""
    tr = _tracker(tmp_path, monkeypatch)
    got = {}
    def open_browser(url):
        got['url'] = url
        # the browser lands on localhost with the code in the QUERY (no
        # fragment with response_type=code) - the server catches it directly
        threading.Timer(
            0.4, lambda: urllib.request.urlopen(
                'http://127.0.0.1:8642/?code=authcode123',
                timeout=5).read()).start()
    monkeypatch.setattr('webbrowser.open', open_browser)
    monkeypatch.setattr(Tracker, '_exchange',
                        lambda self, cid, secret, code, redir:
                        'exchanged-token'
                        if code == 'authcode123' else (_ for _ in ()).throw(
                            AssertionError(code)))
    user = tr.authorize_browser(30700, client_secret='sec', port=8642,
                                timeout=15)
    assert user == {'name': 'tester'}, user
    assert 'response_type=code' in got['url']
    assert 'redirect_uri=http%3A%2F%2Flocalhost%3A8642' in got['url'], got
    saved = open(f'{tmp_path}/anilist_auth.json').read()
    assert 'exchanged-token' in saved and '"enabled": true' in saved


def test_timeout_returns_none(tmp_path, monkeypatch):
    tr = _tracker(tmp_path, monkeypatch)
    monkeypatch.setattr('webbrowser.open', lambda url: None)
    assert tr.authorize_browser(30700, port=8642, timeout=2) is None


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
