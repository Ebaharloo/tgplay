#!/usr/bin/env python3
"""audit_states - screenshot + geometry each UI state of the tgplay window.

Writes ui-audit/stateN*.png and ui-audit/measure.json. No network: the search
debounce is stopped, history is stubbed, no sidebar load is triggered.

Run: env -u PYTHONPATH .venv/bin/python tools/audit_states.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6 import QtCore as C  # noqa: E402
from PySide6 import QtWidgets as W  # noqa: E402

from tp.gui_qt import _app as qt_app  # noqa: E402
from tp import gui_all  # noqa: E402

OUT = os.path.join(ROOT, 'ui-audit')
os.makedirs(OUT, exist_ok=True)

ELEMS = [
    ('search input', 'box'),
    ('results list', 'results'),
    ('history table', 'hist_tbl'),
    ('results stack', 'res_stack'),
    ('shelf', 'shelf'),
    ('title/head', 'head'),
    ('link', 'link_lbl'),
    ('Cast btn', 'cast_btn'),
    ('Simkl list btn', 'add_btn'),
    ('History btn', 'hist_btn'),
    ('episodes table', 'table'),
    ('episodes box', 'ebox'),
    ('options form', 'opts_form'),
    ('status', 'status'),
    ('play from here', 'b_from'),
    ('play only selected', 'b_sel'),
    ('play all', 'b_all'),
    ('stop', 'b_stop'),
    ('close', 'b_close'),
    ('feed table', 'feed'),
    ('history sidebar', 'hist'),
    ('refresh feed&hist', 'side_btn'),
    ('status lights', 'status_strip'),
]


class FakeSession:
    def __init__(self, title='One Piece', n_eps=12, src='agp', audio=False,
                 link='https://animegate.example/watch/one-piece-1074'):
        self.title = title
        self.groups = [{'label': '720p'}, {'label': '1080p'}]
        self.labels = {i: f'Episode {i} - Romance Dawn'
                       for i in range(1, n_eps + 1)}
        self.resume = (5, 0)
        self.src = src
        self.opts = {'skip': 'all', 'f': '1080p',
                     'audio': 'sub' if audio else None}
        self.mpv = []
        self.audio = audio
        self.link = link

    def play(self, c, o, m):
        pass

    def stop(self):
        pass

    def close(self):
        pass

    def status(self):
        return 'playing ep 5'


SHELF = [
    {'title': 'One Piece', 'next_ep': 1074, 'watched': 1073, 'total': 1184,
     'pct': 90.6, 'image': ''},
    {'title': 'KonoSuba', 'next_ep': 8, 'watched': 7, 'total': 10,
     'pct': 70.0, 'image': ''},
    {'title': 'Dandadan', 'next_ep': 3, 'watched': 2, 'total': 12,
     'pct': 16.7, 'image': ''},
]


def hist_rows():
    """Stub for history.recent (cfg is None in this harness)."""
    now = time.time()
    return [
        {'ts': now - 120, 'kind': 'link', 'source': 'agp',
         'title': 'One Piece', 'url': 'agp:one-piece-1074'},
        {'ts': now - 3600, 'kind': 'query', 'source': None,
         'title': 'frieren', 'url': 'frieren'},
        {'ts': now - 3 * 3600, 'kind': 'link', 'source': 'axp',
         'title': 'KonoSuba', 'url': 'axp:konosuba'},
        {'ts': now - 86400, 'kind': 'link', 'source': 'tgp',
         'title': 'Dandadan', 'url': 'tgp:dandadan'},
        {'ts': now - 9 * 86400, 'kind': 'query', 'source': None,
         'title': 'solo leveling', 'url': 'solo leveling'},
    ]


def rect(w, wid):
    p = wid.mapTo(w, C.QPoint(0, 0))
    return {'x': p.x(), 'y': p.y(), 'w': wid.width(), 'h': wid.height(),
            'visible': bool(wid.isVisible())}


def what(wid):
    nm = type(wid).__name__
    if isinstance(wid, (W.QPushButton, W.QToolButton, W.QCheckBox)):
        return f'{nm}:{wid.text()}'
    if isinstance(wid, W.QLineEdit):
        return f'{nm}:{wid.placeholderText() or wid.text()}'
    if isinstance(wid, W.QComboBox):
        return f'{nm}:{wid.currentText()}'
    return nm


def snap(w, name, extra=None):
    app = W.QApplication.instance()
    for _ in range(3):
        app.processEvents()
    w.grab().save(os.path.join(OUT, name + '.png'))
    row = {'state': name, 'window': [w.width(), w.height()],
           'min_size': [w.minimumSizeHint().width(),
                        w.minimumSizeHint().height()],
           'elements': {}}
    for label, attr in ELEMS:
        wid = getattr(w, attr, None)
        if wid is not None:
            row['elements'][label] = rect(w, wid)
    row['elements']['refresh (lights)'] = rect(w, w.status_strip.refresh_btn)
    row['text'] = {
        'head': w.head.text(),
        'status': w.status.text(),
        'status_tooltip_lines': len(w.status.toolTip().splitlines()),
        'link': w.link_lbl.text(),
        'shelf_count': w.shelf.count.text(),
        'episodes_title': w.ebox.title(),
        'stack_page': ('results' if w.res_stack.currentWidget() is w.results
                       else 'history' if w.res_stack.currentWidget() is w.hist_tbl
                       else '?'),
        'results_rows': w.results.count(),
        'hist_rows': w.hist_tbl.rowCount(),
        'episode_rows': w.table.rowCount(),
        'lights': [b.text() for b in w.status_strip._btns.values()],
        'focus': what(W.QApplication.focusWidget()).split(':')[0]
        if W.QApplication.focusWidget() else None,
    }
    box = row['elements']['search input']
    res = row['elements']['results list']
    if box['visible']:
        row['gap_results_bottom_to_search'] = box['y'] - (res['y'] + res['h'])
    if extra:
        row['text'].update(extra)
    return row


def fill_results(w, n=8):
    srcs = ['agp', 'axp', 'tg', 'tgp']
    for i in range(n):
        it = W.QListWidgetItem(
            f'One Piece ({2024 - i})     ·     {srcs[i % 4]}')
        url = f'{srcs[i % 4]}:one-piece-{i}'
        it.setToolTip(url)
        it.setData(C.Qt.UserRole, url)
        it.setData(C.Qt.UserRole + 1, srcs[i % 4])
        it.setData(C.Qt.UserRole + 2, f'One Piece ({2024 - i})')
        it.setData(C.Qt.UserRole + 3, 'result')
        it.setData(C.Qt.UserRole + 4, {'mal': 21})
        w.results.addItem(it)


def tab_walk(w, steps=14):
    """What Tab actually visits, starting from the search box."""
    app = W.QApplication.instance()
    w.box.setFocus()
    app.processEvents()
    seen = [what(app.focusWidget())]
    for _ in range(steps):
        w.focusNextChild()
        app.processEvents()
        seen.append(what(app.focusWidget()))
    w.box.setFocus()
    return seen


def main():
    qt_app()
    w = gui_all.MainWindow(lambda src, target: FakeSession(), cfg=None)
    w._hist_rows = hist_rows                     # no cfg / no disk reads
    w.resize(1180, 820)
    w.show()
    W.QApplication.instance().processEvents()

    states = []

    # 1: cold start - nothing typed, no session, no shelf
    states.append(snap(w, 'state1_cold'))

    # 2: typing a query; debounce stopped before any real search runs
    w.box.setText('one piece')
    w.debounce.stop()
    states.append(snap(w, 'state2_typing'))

    # 3: 8 search results, shelf suppressed
    fill_results(w)
    w.res_stack.setCurrentWidget(w.results)
    w.results.setVisible(True)
    w.res_stack.setVisible(True)
    w.shelf.sync(True)
    states.append(snap(w, 'state3_results'))
    tabs_results = tab_walk(w, 30)

    # 4: history picker (5 rows)
    w.show_history(force=True)
    states.append(snap(w, 'state4_history'))

    # 5: session loaded, 12 episodes, no shelf
    w.set_session(FakeSession())
    states.append(snap(w, 'state5_session'))

    # 6: shelf (3 items) + episodes
    w.shelf.set_items(SHELF)
    w.shelf.sync(False)
    states.append(snap(w, 'state6_shelf'))

    # 7: same content, 1600x1000
    w.resize(1600, 1000)
    W.QApplication.instance().processEvents()
    states.append(snap(w, 'state7_wide'))

    tabs = tab_walk(w, 30)

    # cold start focus: what the window focuses on its own (run() calls
    # box.setFocus() itself, so measure both orders)
    w2 = gui_all.MainWindow(lambda src, target: FakeSession(), cfg=None)
    w2._hist_rows = hist_rows
    w2.resize(1180, 820)
    w2.show()
    W.QApplication.instance().processEvents()
    focus_after_show = what(W.QApplication.focusWidget())
    w2.state['closing'] = True
    for t in (w2.debounce, w2.poll, w2.log_timer, w2.st_timer, w2.side_timer):
        t.stop()
    w2.close()

    data = {'states': states, 'tab_order_results_state': tabs_results,
            'tab_order_from_search': tabs,
            'focus_after_show_no_setfocus': focus_after_show}
    with open(os.path.join(OUT, 'measure.json'), 'w') as f:
        json.dump(data, f, indent=1)

    for st in states:
        print(f"\n== {st['state']}  window={st['window']} "
              f"min={st['min_size']}")
        print('  ' + ' | '.join(f"{k}:{v}" for k, v in st['text'].items()
                                if not isinstance(v, list)))
        if 'gap_results_bottom_to_search' in st:
            print('  results-bottom to search-top:',
                  st['gap_results_bottom_to_search'])
        for k, v in st['elements'].items():
            print(f"  {k:22s} x={v['x']:4d} y={v['y']:4d} "
                  f"w={v['w']:4d} h={v['h']:3d} "
                  f"vis={'Y' if v['visible'] else 'n'}")
    print('\ntab order from search (state7):', tabs)
    print('tab order from search (state3):', tabs_results)
    print('cold-start focus (no setFocus):', focus_after_show)
    w.state['closing'] = True
    for t in (w.debounce, w.poll, w.log_timer, w.st_timer, w.side_timer):
        t.stop()


if __name__ == '__main__':
    main()
