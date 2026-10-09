#!/usr/bin/env python3
"""test_gui - the Tkinter controller passes the right (chosen, opts) to play.

Skips when no display is available. AGP_GUI_TEST auto-acts instead of clicking.
Run: .venv/bin/python tests/test_gui.py   (or python3)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import gui  # noqa: E402


def _opts():
    return {'skip': False, 'skip_toggle': False, 'next': False, 'nowait': False,
            'cut': None, 'f': '720p'}


def test_controller():
    if not gui.available():
        print('SKIP gui (no display)')
        return
    groups = [{'label': '720p'}, {'label': '1080p'}]
    labels = {1: 'Episode 1', 2: 'Episode 2', 3: 'Episode 3'}
    got = {}

    def play(chosen, opts, mpv):
        got['chosen'] = chosen
        got['opts'] = opts

    try:
        os.environ['AGP_GUI_TEST'] = 'play'      # 'Play from here' at resume=2
        gui.controller('Test', 'https://x', groups, labels, 2, _opts(), [],
                       play, one_shot=True)
        assert got['chosen'] == [2, 3], got            # resume=2 -> 2,3
        assert got['opts']['f'] == '720p', got

        os.environ['AGP_GUI_TEST'] = 'all'
        gui.controller('Test', '', groups, labels, None, _opts(), [], play,
                       one_shot=True)
        assert got['chosen'] == [1, 2, 3], got

        # audio dropdown -> opts['audio']
        os.environ['AGP_GUI_TEST'] = 'all'
        gui.controller('Test', '', groups, labels, None, _opts(), [], play,
                       one_shot=True, audio=True)
        assert got['opts'].get('audio') == 'dub', got

        os.environ['AGP_GUI_TEST'] = 'close'     # Close without playing
        gui.controller('Test', '', groups, labels, None, _opts(), [], play,
                       one_shot=True)
    finally:
        os.environ.pop('AGP_GUI_TEST', None)
    print('PASS gui controller (play / all / close)')


def main():
    test_controller()
    print('GUI OK')


if __name__ == '__main__':
    main()
