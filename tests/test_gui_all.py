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


def test_sidebar_click_shows_source_choices():
    try:
        from PySide6 import QtWidgets  # noqa: F401
    except Exception:
        print('SKIP sidebar picker (no PySide6)')
        return
    import time

    import tp.search as search_mod
    import tp.log as tp_log

    made = {}

    class FakeSession:
        title, groups, labels, resume = 'Exact Show', [{'label': 'X'}], {1: 'Ep'}, None
        opts, mpv, audio, link = {}, [], [], None

        def play(self, c, o, m): pass
        def stop(self): pass
        def close(self): pass
        def status(self): return 'idle'

    def loader(src, target):
        made[target] = (src, target)
        return FakeSession()

    # two sources return results; deliberately scrambled order
    fake = [
        {'title': 'Exact Show (2024)', 'url': 'agp:ok',
         'source': 'agp'},
        {'title': 'Totally Different Thing', 'url': 'agp:wrong',
         'source': 'agp'},
        {'title': 'Exact Show', 'url': 'axp:ok', 'source': 'axp'},
    ]
    orig_search = search_mod.search_all
    search_mod.search_all = lambda *a, **k: list(fake)
    orig_sink = tp_log.SINK
    try:
        from tp import gui_all
        from tp.gui_qt import _app as qt_app
        qt_app()
        w = gui_all.MainWindow(loader, cfg=None)
        w.load_entry({'title': 'Exact Show'})
        deadline = time.time() + 2
        while not w._libq.qsize() and time.time() < deadline:
            time.sleep(0.02)
        w._drain_lib()
        assert w.res_stack.currentWidget() is w.results
        assert w.results.count() == 3, w.results.count()
        # best match first (the exact axp row), not auto-loaded
        it = w.results.item(0)
        assert (it.data(C_QT_UserRole(w)) == 'axp:ok'), fake
        assert 'Exact Show' in it.text()
        assert w.state['session'] is None, 'nothing must auto-load'
        # the LINK of each source is visible on its row (so the user can
        # see the exact page per service before choosing)
        for i in range(w.results.count()):
            it = w.results.item(i)
            assert it.data(C_QT_UserRole(w)) and \
                f"↳ {it.data(C_QT_UserRole(w))}" in it.text(), it.text()
        # the user picks: click the agp row
        w._pick_result(w.results.item(1))
        assert 'agp:ok' in made, made      # the CHOSEN source got loaded
        assert w.state['session'] is not None
    finally:
        search_mod.search_all = orig_search
        tp_log.SINK = orig_sink
        try:
            w.state['closing'] = True
            for t in (w.debounce, w.poll, w.log_timer, w.st_timer,
                      w.side_timer):
                t.stop()
            w.deleteLater()
        except Exception:
            pass
    print('PASS sidebar click shows source choices (no random pick)')


def C_QT_UserRole(w):
    from PySide6 import QtCore as C
    return C.Qt.UserRole


def main():
    test_sidebar_click_shows_source_choices()
    test_load_and_play()
    print('GUI_ALL OK')


if __name__ == '__main__':
    main()
