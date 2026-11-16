#!/usr/bin/env python3
"""test_watched - the local watched store and the state -> menu mapping."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import watched  # noqa: E402


class Cfg:
    def __init__(self, p):
        self.watched = p


def _cfg():
    return Cfg(os.path.join(tempfile.mkdtemp(prefix='tgplay-watched-'),
                            'watched.json'))


def test_key_prefers_ids():
    assert watched.key_for('Xian Ni', {'simkl': 42, 'mal': 51289}) == 'simkl:42'
    assert watched.key_for('Xian Ni', {'mal': 51289}) == 'mal:51289'
    assert watched.key_for('Xian Ni!', {}) == 't:xianni'


def test_episode_round_trip():
    cfg = _cfg()
    key = watched.key_for('Xian Ni', {'mal': 51289})
    st = watched.state(cfg, key)
    assert (st['eps'], st['complete']) == (set(), False)

    assert watched.set_episode(cfg, key, 3) is True
    assert watched.set_episode(cfg, key, 3) is False           # toggle off
    assert watched.set_episode(cfg, key, 3, True) is True      # explicit set
    assert watched.state(cfg, key)['eps'] == {3}

    cfg2 = _cfg()                                    # fresh Config, same file
    cfg2.watched = cfg.watched
    assert watched.state(cfg2, key)['eps'] == {3}    # survives a restart


def test_season_and_complete():
    cfg = _cfg()
    key = 'mal:51289'
    assert watched.set_season(cfg, key, [1, 2, 3], True) is True
    assert watched.state(cfg, key)['eps'] == {1, 2, 3}
    assert watched.set_season(cfg, key, [1, 2, 3], False) is False
    assert watched.state(cfg, key)['eps'] == set()

    assert watched.set_complete(cfg, key) is True
    assert watched.state(cfg, key)['complete'] is True
    assert watched.set_complete(cfg, key) is False


def test_change_returns_hook_payload():
    cfg = _cfg()
    key = 'mal:1'
    assert watched.change(cfg, key, 'episode', 2, [1, 2], None) == \
        ('episode', True)
    assert watched.change(cfg, key, 'season', 1, [1, 2], None) == \
        ('season', True)
    assert watched.change(cfg, key, 'season_unwatched', 1, [1, 2], None) == \
        ('season_unwatched', False)
    assert watched.change(cfg, key, 'series', 1, [1, 2], None) == \
        ('series', True)
    try:
        watched.change(cfg, key, 'nope', 1, [1, 2])
    except ValueError:
        pass
    else:
        raise AssertionError('unknown kind must raise')
    st = watched.state(cfg, key)
    assert (st['eps'], st['complete']) == (set(), True)


def test_rows_mapping():
    nums = [1, 2, 3]
    empty = {'eps': set(), 'complete': False}
    rows = watched.rows(empty, 1, nums)
    assert rows[0] == ('episode', 'Mark watched', False, True), rows[0]
    assert rows[1] == ('season', 'Mark whole season watched', False, True)
    assert rows[2][0] == 'season_unwatched' and rows[2][3] is False
    assert rows[3] == ('series', 'Mark series complete', False, True)

    seen = {'eps': {1}, 'complete': True}
    rows = watched.rows(seen, 1, nums)
    assert rows[0][:3] == ('episode', 'Mark unwatched', True), rows[0]
    assert rows[1][3] is True                      # more to mark watched
    assert rows[2][3] is True                       # something to unmark
    assert rows[3][:3] == ('series', 'Unmark complete', True), rows[3]

    full = {'eps': set(nums), 'complete': False}
    rows = watched.rows(full, 2, nums)
    assert rows[1][3] is False                      # nothing left to mark


def test_unreadable_store_is_empty():
    cfg = Cfg(os.path.join(tempfile.mkdtemp(prefix='tgplay-watched-'),
                           'missing-dir', 'watched.json'))
    st = watched.state(cfg, 'mal:1')
    assert (st['eps'], st['complete']) == (set(), False)
    watched.set_episode(cfg, 'mal:1', 1)            # save_json makes the dir
    assert watched.state(cfg, 'mal:1')['eps'] == {1}


def test_qt_menu_persists_and_emits_hook():
    """The Qt episode table call site: mark, repaint, hook, survives reload."""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from tp import gui_all
    from tp.config import Config
    from tp.gui_qt import _app

    class FakeSession:
        src = 'axp'
        audio = True
        link = None
        groups = [{'label': 'X'}]
        title = 'Xian Ni'
        mal_id = 51289
        resume = None
        opts, mpv = {}, []

        def __init__(self):
            self.labels = {1: 'Ep 1', 2: 'Ep 2', 3: 'Ep 3'}

        def play(self, c, o, m): pass
        def stop(self): pass
        def close(self): pass
        def status(self): return 'idle'

    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-watched-gui-'))
    _app()
    win = gui_all.MainWindow(lambda src, target: FakeSession(), cfg=cfg)
    seen = []
    win.on_watched_changed = lambda kind, on, info: seen.append((kind, on))
    win.set_session(FakeSession())
    assert win.table.item(1, 1).text() == 'Ep 2'          # not watched yet

    win._mark_watched('episode', 2, win._all_nums())
    assert seen == [('episode', True)], seen
    assert win.table.item(1, 0).text() == '✓ 2'
    assert watched.state(cfg, 'mal:51289')['eps'] == {2}

    win._mark_watched('season', 1, win._all_nums())
    assert ('season', True) in seen
    assert watched.state(cfg, 'mal:51289')['eps'] == {1, 2, 3}
    assert win.table.item(2, 0).text() == '✓ 3'
    win.close()
