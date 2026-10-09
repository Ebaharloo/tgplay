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

        os.environ['AGP_GUI_TEST'] = 'close'     # Close without playing
        gui_qt.controller('Test', '', groups, labels, None, _opts(), [], play,
                          one_shot=True)
    finally:
        os.environ.pop('AGP_GUI_TEST', None)
    print('PASS gui_qt controller (play / all / close)')


def main():
    test_controller()
    print('GUI-QT OK')


if __name__ == '__main__':
    main()
