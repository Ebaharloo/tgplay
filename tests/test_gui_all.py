#!/usr/bin/env python3
"""test_gui_all - the unified window loads a session and plays it."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from tp import gui_all  # noqa: E402


class FakeSession:
    def __init__(self, title, labels, groups, audio=False, link=None):
        self.title = title
        self.groups = groups
        self.labels = labels
        self.resume = None
        self.opts = {'skip': 'all',
                     'f': groups[0]['label'] if groups else None,
                     'audio': 'dub'}
        self.mpv = []
        self.audio = audio
        self.link = link
        self.played = None
        self.closed = False

    def play(self, c, o, m):
        self.played = c

    def stop(self):
        pass

    def close(self):
        self.closed = True

    def status(self):
        return 'idle'


def test_load_and_play():
    try:
        from PySide6 import QtWidgets  # noqa: F401
    except Exception:
        print('SKIP gui_all (no PySide6)')
        return
    made = {}

    def loader(src, target):
        s = FakeSession(f'Show {src}', {1: 'Ep 1', 2: 'Ep 2'},
                        [{'label': '720p'}], audio=(src == 'axp'),
                        link='https://x')
        made[target] = s
        return s

    os.environ['AGP_GUI_TEST'] = 'play'
    try:
        gui_all.app(loader, cfg=None, one_shot=True, initial=('agp', 'u1'))
    finally:
        os.environ.pop('AGP_GUI_TEST', None)
    assert made['u1'].played == [1, 2], made['u1'].played
    assert made['u1'].closed, 'session should be closed on window close'
    print('PASS gui_all loads a session and plays all')


def main():
    test_load_and_play()
    print('GUI_ALL OK')


if __name__ == '__main__':
    main()
