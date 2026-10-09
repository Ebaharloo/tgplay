#!/usr/bin/env python3
"""test_gui - the Tkinter menu returns the right (chosen, opts, mpv).

Skips when no display is available. Uses AGP_GUI_TEST to auto-act instead of
clicking. Run: .venv/bin/python tests/test_gui.py   (or python3)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import gui  # noqa: E402


def _opts():
    return {'skip': False, 'skip_toggle': False, 'next': False, 'nowait': False,
            'cut': None, 'f': '720p'}


def test_configure():
    if not gui.available():
        print('SKIP gui (no display)')
        return
    groups = [{'label': '720p'}, {'label': '1080p'}]
    labels = {1: 'Episode 1', 2: 'Episode 2', 3: 'Episode 3'}
    try:
        os.environ['AGP_GUI_TEST'] = 'play'          # 'Play from here' at resume
        out = gui.configure('Test', 'https://x', groups, labels, 2, _opts(), [])
        assert out is not None
        chosen, opts, mpv = out
        assert chosen == [2, 3], chosen              # resume=2 -> 2,3
        assert opts['f'] == '720p'

        os.environ['AGP_GUI_TEST'] = 'all'
        chosen, _o, _m = gui.configure('Test', '', groups, labels, None, _opts(), [])
        assert chosen == [1, 2, 3], chosen

        os.environ['AGP_GUI_TEST'] = 'cancel'
        assert gui.configure('Test', '', groups, labels, None, _opts(), []) is None
    finally:
        os.environ.pop('AGP_GUI_TEST', None)
    print('PASS gui configure (play / all / cancel)')


def main():
    test_configure()
    print('GUI OK')


if __name__ == '__main__':
    main()
