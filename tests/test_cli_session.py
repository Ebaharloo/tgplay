#!/usr/bin/env python3
"""test_cli_session - every CLI path (direct / curses) goes through Session.

The agp/axp/tgp mains build ONE Session and play through it; this proves the
wiring picks the right episodes and closes the session afterwards.
Run: .venv/bin/python tests/test_cli_session.py
"""
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tp import cli  # noqa: E402


class FakeProvider:
    title = 'Fake Show'

    def episodes(self):
        return {1: 'Episode 1', 2: 'Episode 2', 3: 'Episode 3'}

    groups = []

    def select(self, quality=None):
        return self

    def stream(self, num):
        return object()


class FakeSession:
    """Mimics Session's CLI-facing surface (play/close/resume/labels)."""

    def __init__(self):
        self.provider = FakeProvider()
        self.groups = []
        self.resume = None
        self.labels = dict(self.provider.episodes())
        self.played = []
        self.closed = False

    def play(self, chosen, o, m):
        self.played.append((list(chosen), dict(o), list(m)))

    def close(self):
        self.closed = True


class FakeTracker:
    def __init__(self, *a, **k):
        pass

    def enabled(self):
        return False


def _cfg():
    import os
    import tempfile
    from tp.config import Config
    home = tempfile.mkdtemp(prefix='tgplay-cli-')
    os.environ['AGP_CONFIG_DIR'] = home     # isolates ui.json writes, if any
    return Config()


def test_direct_play_uses_session():
    s = FakeSession()
    _cfg()
    with mock.patch('tp.session.open_session', lambda *a, **k: s), \
            mock.patch('tp.tracking.Tracker', FakeTracker):
        rc = cli.main(['https://animegate.ir/anime/x-1', '-e', '2-3',
                       '--no-sync', '--skip=names'])
    assert rc == 0, rc
    assert s.closed, 'direct play must close the session (proxy stop)'
    assert len(s.played) == 1
    chosen, o, m = s.played[0]
    assert chosen == [2, 3], chosen          # -e 2-3 -> just those episodes
    assert o['skip'] == 'names' and o['sync'] == 'off', o
    print('PASS direct play builds one Session, closes it after')


def test_direct_all_episodes():
    s = FakeSession()
    _cfg()
    with mock.patch('tp.session.open_session', lambda *a, **k: s), \
            mock.patch('tp.tracking.Tracker', FakeTracker):
        rc = cli.main(['https://animegate.ir/anime/x-1', '-a'])
    assert rc == 0, rc
    chosen, o, m = s.played[0]
    assert chosen == [1, 2, 3], chosen       # -a -> all, in order
    print('PASS -a plays every episode through the Session')


def test_single_episode_flag():
    s = FakeSession()
    _cfg()
    with mock.patch('tp.session.open_session', lambda *a, **k: s), \
            mock.patch('tp.tracking.Tracker', FakeTracker):
        cli.main(['https://animegate.ir/anime/x-1', '-e', '2'])
    chosen, o, _m = s.played[0]
    assert chosen == [2], chosen
    print('PASS -e single-episode play')


def main():
    test_direct_play_uses_session()
    test_direct_all_episodes()
    test_single_episode_flag()
    print('CLI-SESSION OK')


if __name__ == '__main__':
    main()
