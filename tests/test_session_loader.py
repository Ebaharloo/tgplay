#!/usr/bin/env python3
"""test_session_loader - the OOP seams every GUI entry point now goes through.

- SessionLoader: option precedence (CLI base > saved setup > defaults),
  and that it delegates to tp.session.open_session with the merged opts.
- UnifiedWindow: runs the unified app and passes loader/cfg/initial through
  (headless via AGP_GUI_TEST='close').

Run: .venv/bin/python tests/test_session_loader.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from unittest import mock  # noqa: E402

from tp import session  # noqa: E402
from tp import setup as setup_mod  # noqa: E402


class Cfg:
    def __init__(self, p):
        self.progress = p
        self.ui = p
        self.cache_dir = os.path.join(os.path.dirname(p), 'cache')
        self.cache_budget = 1
        self.proxy_port = 0
        self.tg_session = ''
        self.translations = os.path.join(os.path.dirname(p), 'translations.json')
        self.ep_titles = os.path.join(os.path.dirname(p), 'ep_titles.json')
        self.mal_ids = os.path.join(os.path.dirname(p), 'mal_ids.json')


def test_opts_precedence():
    cfg = Cfg(os.path.join(tempfile.mkdtemp(prefix='tp-load-'), 'ui.json'))
    # remember a previous session's setup for 'axp'
    setup_mod.save(cfg.ui,
                       {'skip': 'all', 'f': '1080p', 'next': 0.6,
                        'skip_toggle': False, 'cut': None, 'nowait': False},
                       [], 'axp')

    loader = session.SessionLoader(cfg, http=None,
                                   base_opts={'skip': 'names'},   # CLI wins
                                   base_mpv=['--volume=50'])
    o, m = loader.opts_for('axp')
    assert o['skip'] == 'names', o                 # CLI beats saved
    assert o['f'] == '1080', o                     # saved quality fills in
    assert o['next'] == 0.6, o
    assert m == ['--volume=50'], m

    # a fresh loader (tgplay path: no CLI base) applies the saved setup alone
    o2, m2 = session.SessionLoader(cfg, http=None).opts_for('axp')
    assert o2['skip'] == 'all' and o2['f'] == '1080', o2
    assert m2 == [], m2
    print('PASS SessionLoader option precedence')


def test_loader_delegates():
    opened = {}

    def fake_open(src, target, cfg, http, opts=None, mpv=None):
        opened['args'] = (src, target, opts, mpv)
        return 'SESSION'

    cfg = Cfg(os.path.join(tempfile.mkdtemp(prefix='tp-load-'), 'ui.json'))
    with mock.patch.object(session, 'open_session', fake_open):
        got = session.SessionLoader(
            cfg, http=None, base_opts={'f': '1080p'})('axp', 'some-slug')
    assert got == 'SESSION', got
    src, target, opts, _mpv = opened['args']
    assert (src, target) == ('axp', 'some-slug'), opened['args']
    assert opts['f'] == '1080p', opts
    # make_loader still returns a callable loader for gui_all
    loader = session.make_loader(cfg, http=None)
    assert callable(loader) and isinstance(loader, session.SessionLoader)
    print('PASS SessionLoader -> open_session delegation')


def test_unified_window():
    try:
        from PySide6 import QtWidgets  # noqa: F401
    except Exception:
        print('SKIP UnifiedWindow (no PySide6)')
        return
    from tp import gui_all

    class FakeSession:
        title, groups, labels, resume = ('ok', [{'label': '720p'}],
                                         {1: 'Ep'}, None)
        src = 'agp'
        opts, mpv, audio, link = {}, [], [], 'https://x'

        def play(self, c, o, m): pass
        def stop(self): pass
        def close(self): pass
        def status(self): return 'idle'

    got = {}

    def loader(src, target):
        got['args'] = (src, target)
        return FakeSession()

    os.environ['AGP_GUI_TEST'] = 'close'
    try:
        gui_all.UnifiedWindow(loader, cfg=None, initial=('agp', 'u1')).run()
    finally:
        os.environ.pop('AGP_GUI_TEST', None)
    assert got['args'] == ('agp', 'u1'), got
    print('PASS UnifiedWindow opens the unified app with the given loader')


def test_axp_episode_labels_cleaned():
    """The AnimeX API embeds Bangumi's 'Release: date - ' marker in episode
    titles of ALREADY-aired episodes; sessions must present the name only."""
    reload = os.environ.setdefault  # noqa - keep imports local like the file

    class FakeAX:
        title = 'Chainsmoker Cat'

        def __init__(self, target, quality=None, audio=None, http=None):
            self.groups = []
            self._eps = {9: 'Release: 2026/09/03 15:00 GMT - Little Sis',
                         10: 'Fine Name'}

        def set_audio(self, a):
            return self

        def fetch_groups(self):
            return []

        def select(self, q=None):
            return self

        def episodes(self):
            return dict(self._eps)

    home = tempfile.mkdtemp(prefix='tgplay-axp-labels-')
    cfg = Cfg(os.path.join(home, 'progress.json'))
    with mock.patch('tp.providers.animex.AnimeXProvider', FakeAX), \
            mock.patch('tp.session._safe_mal', lambda *a, **k: None), \
            mock.patch('tp.cli._link_get', lambda *a, **k: 'https://x'):
        s = session.open_session('axp', 'axp:whatever', cfg, http=None,
                                 opts={}, mpv=[])
    assert s.labels[9] == 'Little Sis', s.labels
    assert s.labels[10] == 'Fine Name', s.labels
    print('PASS axp session labels cleaned of release-date prefixes')


def main():
    test_opts_precedence()
    test_loader_delegates()
    test_axp_episode_labels_cleaned()
    test_unified_window()
    print('SESSION-LOADER OK')


if __name__ == '__main__':
    main()
