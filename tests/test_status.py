#!/usr/bin/env python3
"""test_status - the connection lights: Simkl / AnimeGate / AniList probes.

Fully mocked (no network): each service's state and its 'fix' hint.
Run: .venv/bin/python tests/test_status.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.config import Config   # noqa: E402
from tp.status import StatusProbe  # noqa: E402


class FakeAccount:
    def __init__(self, client_id='cid', logged_in=True, user='tester'):
        self.client_id = client_id
        self._in = logged_in
        self._user = user

    def logged_in(self):
        return self._in

    def user(self):
        return self._user


class FakeGate:
    def __init__(self, alive=True, reason='ok'):
        self._alive = alive
        self._reason = reason

    def alive(self):
        return self._alive, self._reason


def test_simkl_states():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-st-')).ensure()
    p = StatusProbe(cfg, account=FakeAccount(client_id=None))
    it = p.check_simkl()
    assert it['state'] == 'bad' and it['fix'] == 'simkl', it
    p = StatusProbe(cfg, account=FakeAccount(logged_in=False))
    it = p.check_simkl()
    assert it['state'] == 'bad' and 'not connected' in it['detail'], it
    p = StatusProbe(cfg, account=FakeAccount(user='tester'))
    it = p.check_simkl()
    assert it['state'] == 'ok' and 'tester' in it['detail'], it
    p = StatusProbe(cfg, account=FakeAccount(user=None))
    it = p.check_simkl()
    assert it['state'] == 'warn' and 'token' in it['detail'], it
    print('PASS Simkl light: bad / warn / ok + fix hint')


def test_gate_states():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-st-')).ensure()
    ok = StatusProbe(cfg, gate=FakeGate(True, 'ok')).check_gate()
    assert ok['state'] == 'ok' and ok['key'] == 'gate', ok
    bad = StatusProbe(cfg, gate=FakeGate(False, 'logged out')).check_gate()
    assert bad['state'] == 'bad' and 'login page' in bad['detail'], bad
    print('PASS AnimeGate light: ok / bad + login fix')


def test_anilist_light():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-st-')).ensure()
    it = StatusProbe(cfg).check_anilist()
    assert it['state'] == 'warn' and it['fix'] == 'anilist', it
    # the Tracker reads {'token': ...} (anilist.json) - the old probe looked
    # for 'access_token' and stayed warn even when connected
    json.dump({'token': 'tok', 'enabled': True},
              open(cfg.anilist_auth, 'w'))
    it = StatusProbe(cfg).check_anilist()
    assert it['state'] == 'ok', it
    print('PASS AniList light: optional off -> ok with token')


def test_check_all_is_independent():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-st-')).ensure()

    class Exploding:
        def check_simkl(self):
            raise RuntimeError('boom')

    p = StatusProbe(cfg, gate=FakeGate(True, 'ok'))
    p.check_simkl = Exploding().check_simkl     # one bad service
    items = p.check_all()
    assert len(items) == 3, items
    assert [i['key'] for i in items] == ['simkl', 'gate', 'anilist'], items
    assert items[0]['state'] == 'warn', items[0]        # fails soft
    assert items[1]['state'] == 'ok', items[1]          # others unaffected
    print('PASS one failing probe never hides the other lights')


def test_strip_widget():
    """The lights widget: colours follow the states, clicks carry the item."""
    from PySide6 import QtWidgets  # noqa: F401
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from tp.gui_qt import _app as qt_app
    qt_app()
    from tp.gui_all import StatusStrip
    got = {}
    s = StatusStrip(lambda it: got.setdefault('item', it), lambda: None)
    s.set_items([
        {'key': 'simkl', 'name': 'Simkl', 'state': 'ok',
         'detail': 'connected as X', 'fix': 'simkl'},
        {'key': 'gate', 'name': 'AnimeGate', 'state': 'bad',
         'detail': 'logged out', 'fix': 'gate'},
    ])
    assert s._btns['simkl'].text() == '● Simkl'
    assert '#98c379' in s._btns['simkl'].styleSheet()      # green
    assert '#e06c75' in s._btns['gate'].styleSheet()       # red
    s._btns['gate'].click()
    assert got['item']['key'] == 'gate'
    print('PASS status strip colours + click fix hint')


def main():
    test_simkl_states()
    test_gate_states()
    test_anilist_light()
    test_check_all_is_independent()
    test_strip_widget()
    print('STATUS OK')


if __name__ == '__main__':
    main()
