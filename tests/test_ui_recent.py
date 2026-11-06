#!/usr/bin/env python3
"""test_ui_recent - rail switch, settings dialog, sidebar column, one refresh.

PLAN-RECENT F6 cases 11-14, offscreen Qt with a stub loader and a fake
library.overview (no network, no Simkl, no mpv).
Run: env -u PYTHONPATH .venv/bin/python -m pytest tests/test_ui_recent.py -q
"""
import os
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['AGP_NO_TRACK'] = '1'

import pytest  # noqa: E402

from tp.config import Config, load_json, save_json  # noqa: E402


def _ui_row(title, n=0):
    """A library row that needs no network: no poster, no mal -> no image."""
    return {'title': title, 'simkl': 1 + n, 'mal': None, 'anilist': None,
            'status': 'watching', 'watched': 4, 'total': 12, 'next_ep': 5,
            'air_date': date.today().isoformat() + 'T00:00:00Z',
            'last_watched': date.today().isoformat() + 'T00:00:00Z',
            'poster': ''}


@pytest.fixture
def win(monkeypatch, tmp_path):
    from tp import gui_all as GA
    from tp import log as tp_log
    from tp.gui_qt import _app
    from tp.simkl_account import SimklAccount
    app = _app()
    monkeypatch.setattr(GA.MainWindow, 'load_side', lambda self: None)
    # relations/episodes are network: the worker path is stubbed in UI tests
    monkeypatch.setattr(GA.MainWindow, '_fetch_extra',
                        staticmethod(lambda *a, **k: ({}, {}, {})))
    monkeypatch.setattr(SimklAccount, 'logged_in', lambda self: True)
    w = GA.MainWindow(lambda src, target: None,
                      cfg=Config(home=str(tmp_path)).ensure())
    yield w
    for t in (w.debounce, w.poll, w.log_timer, w.st_timer, w.side_timer):
        t.stop()
    tp_log.SINK = w._prev_sink
    w.hide()
    w.deleteLater()
    app.processEvents()


def _pump(win, pred, secs=5.0):
    """Run the GUI loop until pred() or the deadline (worker -> _libq)."""
    from tp.gui_qt import _app
    deadline = time.time() + secs
    while time.time() < deadline:
        _app().processEvents()
        win._drain_lib()
        if pred():
            return True
        time.sleep(0.02)
    return False


def _feed_titles(win):
    return [win.feed.item(r, 2).text() for r in range(win.feed.rowCount())
            if win.feed.item(r, 2) is not None]


# --- 11. rail buttons swap the data, nothing else moves ------------------
def test_11_rail_switch_keeps_the_layout(win):
    from tp.gui_qt import _app
    win.show()
    _app().processEvents()
    win._rails = {'continue': [{'title': 'A', 'pct': 1.0},
                               {'title': 'A2', 'pct': 2.0}],
                  'recent': [{'title': 'B', 'pct': 3.0},
                             {'title': 'B2', 'pct': 4.0}]}
    win._rail_mode('continue')
    _app().processEvents()
    before = {n: getattr(win, n).geometry()
              for n in ('box', 'results', 'table')}
    assert [i['title'] for i in win.shelf._items] == ['A', 'A2']

    win.shelf.rails['recent'].click()
    _app().processEvents()
    assert [i['title'] for i in win.shelf._items] == ['B', 'B2'], \
        win.shelf._items
    assert win.shelf.row.itemAt(0).widget().item['title'] == 'B'

    after = {n: getattr(win, n).geometry() for n in before}
    assert after == before, (before, after)      # fixed-slot invariant
    win.shelf.rails['continue'].click()
    _app().processEvents()
    assert [i['title'] for i in win.shelf._items] == ['A', 'A2']


# --- 12. gear dialog saves to ui.json, shelf honours the limit -----------
def test_12_dialog_roundtrip_and_shelf_limit(win, monkeypatch):
    from tp import gui_all as GA
    from tp import library as lib
    rows = [_ui_row(f'Show {i}', i) for i in range(3)]
    monkeypatch.setattr(lib, 'overview', lambda *a, **k: {
        'cal': rows, 'rem': rows, 'hist': rows, 'rows': rows})
    win.shelf.set_mode('recent')
    dlg = GA.RailsDialog(win._cfg, win, on_save=win._on_rails_saved)
    assert dlg.recent_limit.value() == 20         # defaults shown
    dlg.recent_limit.setValue(2)
    dlg.side_show.setChecked(False)
    dlg.apply()

    saved = load_json(win._cfg.ui)['window']['rails']
    assert saved['recent']['limit'] == 2, saved
    assert saved['sidebar']['show_days'] is False, saved

    assert _pump(win, lambda: len(win._rails['recent']) == 2), win._rails
    assert len(win.shelf._items) == 2, win.shelf._items
    assert win.feed.isColumnHidden(3), 'Aired column must follow show_days'


# --- 13. sidebar Aired column appears/disappears with show_days ----------
def test_13_aired_column_follows_show_days(win):
    from tp import gui_all as GA
    assert win.feed.horizontalHeaderItem(3).text() == 'Aired'
    save_json(win._cfg.ui, {'window': {'rails': {'sidebar':
                                                 {'show_days': False}}}})
    win._apply_rails()
    assert win.feed.isColumnHidden(3)

    dlg = GA.RailsDialog(win._cfg, win, on_save=win._on_rails_saved)
    assert not dlg.side_show.isChecked()          # read from ui.json
    dlg.side_show.setChecked(True)
    dlg.apply()
    assert not win.feed.isColumnHidden(3)
    assert load_json(win._cfg.ui)['window']['rails']['sidebar']['show_days']


# --- 14. one refresh updates shelf + feed + hist + recent ----------------
def test_14_one_refresh_updates_every_view(win, monkeypatch):
    from tp import library as lib
    calls = {'n': 0}

    def fake_overview(*_a, **_k):
        calls['n'] += 1
        rows = [_ui_row(f'Show{calls["n"]}')]
        return {'cal': rows, 'rem': rows, 'hist': rows, 'rows': rows}
    monkeypatch.setattr(lib, 'overview', fake_overview)
    got = []

    def fake_extra(cfg, http, rows, days):
        got.append(days)
        return ({}, {}, {})
    monkeypatch.setattr(win, '_fetch_extra', fake_extra)
    win.shelf.set_mode('recent')

    win._refresh_library()
    assert _pump(win, lambda: win.state.get('recent')
                 and win.state['recent'][0]['title'] == 'Show1'), 'call 1'
    assert [i['title'] for i in win._rails['recent']] == ['Show1']
    assert 'Show1' in ' '.join(_feed_titles(win)), _feed_titles(win)
    assert 'Show1' in ' '.join(win.hist.item(r, 2).text()
                               for r in range(win.hist.rowCount()))
    assert got == [14], got          # relations/episodes fetched on the worker

    win._refresh_library()                        # Simkl changed in between
    assert _pump(win, lambda: win.state.get('recent')
                 and win.state['recent'][0]['title'] == 'Show2'), 'call 2'
    assert [i['title'] for i in win._rails['recent']] == ['Show2']
    assert [i['title'] for i in win.shelf._items] == ['Show2']
    assert 'Show2' in ' '.join(_feed_titles(win)), _feed_titles(win)
    assert 'Show2' in ' '.join(win.hist.item(r, 2).text()
                               for r in range(win.hist.rowCount()))
