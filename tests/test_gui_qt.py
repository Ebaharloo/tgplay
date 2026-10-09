#!/usr/bin/env python3
"""test_gui_qt - the Qt (PySide6) controller passes the right (chosen, opts).

Runs headless via the 'offscreen' Qt platform. Skips when PySide6 is missing.
AGP_GUI_TEST auto-acts instead of clicking.
Run: .venv/bin/python tests/test_gui_qt.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from tp import gui_qt  # noqa: E402


def _opts():
    return {'skip': False, 'skip_toggle': False, 'next': False, 'nowait': False,
            'cut': None, 'f': '720p'}


def test_controller():
    if not gui_qt.available():
        print('SKIP gui_qt (no display / PySide6)')
        return
    groups = [{'label': '720p'}, {'label': '1080p'}]
    labels = {1: 'Episode 1', 2: 'Episode 2', 3: 'Episode 3'}
    got = {}

    def play(chosen, opts, mpv):
        got['chosen'] = chosen
        got['opts'] = opts

    try:
        os.environ['AGP_GUI_TEST'] = 'play'      # 'Play from here' at resume=2
        gui_qt.controller('Test', 'https://x', groups, labels, 2, _opts(), [],
                          play, one_shot=True)
        assert got['chosen'] == [2, 3], got            # resume=2 -> 2,3
        assert got['opts']['f'] == '720p', got

        os.environ['AGP_GUI_TEST'] = 'all'
        gui_qt.controller('Test', '', groups, labels, None, _opts(), [], play,
                          one_shot=True)
        assert got['chosen'] == [1, 2, 3], got

        # the audio dropdown is returned as opts['audio'] when enabled
        os.environ['AGP_GUI_TEST'] = 'all'
        gui_qt.controller('Test', '', groups, labels, None, _opts(), [], play,
                          one_shot=True, audio=True)
        assert got['opts'].get('audio') == 'dub', got

        os.environ['AGP_GUI_TEST'] = 'close'     # Close without playing
        gui_qt.controller('Test', '', groups, labels, None, _opts(), [], play,
                          one_shot=True)
    finally:
        os.environ.pop('AGP_GUI_TEST', None)
    print('PASS gui_qt controller (play / all / close)')


def main():
    test_controller()
    test_launcher_route_link()
    test_launcher_enter_without_result_keeps_open()
    print('GUI-QT OK')


def test_launcher_route_link():
    if not gui_qt.available():
        print('SKIP gui_qt launcher (no display / PySide6)')
        return
    from PySide6 import QtWidgets as W, QtCore as C
    app = W.QApplication.instance() or W.QApplication([])

    def drive():
        for w in app.topLevelWidgets():
            if isinstance(w, W.QDialog) and w.isVisible():
                box = w.findChild(W.QLineEdit)
                if box is not None:
                    box.setText('https://animex.one/anime/foo-1')
                    box.returnPressed.emit()      # triggers ok()
                    return
    C.QTimer.singleShot(300, drive)
    res = gui_qt.launcher()
    assert res == ('axp', 'https://animex.one/anime/foo-1'), res
    print('PASS gui_qt launcher routes a pasted link')


def test_launcher_enter_without_result_keeps_open():
    if not gui_qt.available():
        print('SKIP gui_qt launcher (no display / PySide6)')
        return
    from PySide6 import QtWidgets as W, QtCore as C
    import tp.search as searchmod
    old = searchmod.search_all
    searchmod.search_all = lambda *a, **k: []     # no results, no network
    app = W.QApplication.instance() or W.QApplication([])
    st = {'win': None, 'stayed': False}

    def drive():
        for w in app.topLevelWidgets():
            if isinstance(w, W.QDialog) and w.isVisible():
                st['win'] = w
                box = w.findChild(W.QLineEdit)
                box.setText('zzz-no-such-title')
                C.QTimer.singleShot(1200, lambda: box.returnPressed.emit())

                def check():
                    st['stayed'] = w.isVisible()
                    w.reject()
                C.QTimer.singleShot(1500, check)
                return
        C.QTimer.singleShot(200, drive)
    try:
        C.QTimer.singleShot(200, drive)
        res = gui_qt.launcher()
    finally:
        searchmod.search_all = old
    assert res is None, res
    assert st['stayed'], 'window must stay open when Enter has no result'
    print('PASS gui_qt launcher: empty Enter keeps the window open')


if __name__ == '__main__':
    main()
