#!/usr/bin/env python3
"""test_characters - the cast service: parsing, cache-first opens and the
Bangumi (Chinese) boost - fully mocked, no network.
Run: .venv/bin/python tests/test_characters.py
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import characters as ch   # noqa: E402
from tp.config import Config      # noqa: E402

MEDIA = {
    'id': 115844, 'idMal': 41219,
    'title': {'romaji': 'Fanren Xiu Xian Zhuan',
              'english': "A Record Of Mortal's Journey To Immortality",
              'native': '凡人修仙传：风起天南'},
    'characters': {'edges': [
        {'role': 'MAIN',
         'voiceActors': [{'name': {'full': 'Wenqing Qian'},
                          'language': 'JAPANESE'}],
         'node': {'id': 230157,
                  'name': {'full': 'Li Han', 'native': '韩立'},
                  'image': {'large': 'https://img/1.jpg'},
                  'favourites': 35,
                  'description': 'Han Li, cautious cultivator.',
                  'siteUrl': 'https://anilist.co/character/230157'}},
        {'role': 'SUPPORTING', 'voiceActors': [],
         'node': {'id': 99, 'name': {'full': 'Nan Gong', 'native': '南宫婉'},
                  'image': {}, 'favourites': 2, 'description': '',
                  'siteUrl': ''}},
    ]}}


def test_parse():
    rows = ch._rows_from_anilist(MEDIA)
    assert len(rows) == 2, rows
    assert rows[0]['name'] == 'Li Han' and rows[0]['native'] == '韩立'
    assert rows[0]['role'] == 'main' and rows[0]['va'] == 'Wenqing Qian'
    assert rows[0]['url'].endswith('230157')
    assert rows[1]['va'] == '' and rows[1]['role'] == 'supporting'
    print('PASS AniList edges parsed (names, native, role, VA, link)')


def _mk_rec():
    return {'fetched': time.time(), 'anilist_id': MEDIA['id'],
            'mal': 41219, 'show': 'Fanren Xiu Xian Zhuan',
            'native_titles': ['凡人修仙传：风起天南'],
            'rows': ch._rows_from_anilist(MEDIA)}


def test_cache_first():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-cast-')).ensure()
    svc = ch.CharactersService(cfg, http=None)

    def fake_anilist(mal_id, title):
        rec = _mk_rec()
        svc._put(f'mal:{rec["mal"]}', rec)        # _anilist persists too
        return rec

    svc._anilist = fake_anilist
    rec = svc.fetch(mal_id=41219)
    assert rec and len(rec['rows']) == 2
    hit = svc.cached(mal_id=41219)
    assert hit and hit['rows'][0]['name'] == 'Li Han'
    # key is the pinned MAL id -> instant, no network on reopen
    stored = json.load(open(cfg.characters))
    assert 'mal:41219' in stored, list(stored)
    # an expired record is a cache MISS (background refresh will run)
    stored['mal:41219']['fetched'] -= ch.CAST_TTL * 2
    json.dump(stored, open(cfg.characters, 'w'))
    assert svc.cached(mal_id=41219) is None
    print('PASS cache-first + TTL miss')


def test_bangumi_boost():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-cast-')).ensure()

    class FakeBgm:
        def subject_id(self, kw):
            assert '凡人' in kw                      # searched by CN title
            return 345768

        def subject_characters(self, sid):
            return [{'id': 5, 'name': '韩立', 'role': 1,
                     'actors': [{'name': 'Yuanjiang Bao'}],
                     'stat': {'favorites': 10}, 'images': {},
                     'short_desc': 'CN entry.'}]

    svc = ch.CharactersService(cfg, http=None, bangumi=FakeBgm())
    svc._anilist = lambda mal_id, title: _mk_rec()
    rec = svc.fetch(mal_id=41219)
    names = [r['name'] for r in rec['rows']]
    assert '韩立' in names and rec.get('has_cn'), names   # CN row merged
    assert any(r['va'] == 'Yuanjiang Bao' for r in rec['rows'])
    print('PASS Bangumi boost merges CN characters + CN voice actors')


def test_dialog_headless():
    """CastDialog is pure widget code: build it with a stub service, deliver
    a rec through the worker queue and check rows + detail pane render."""
    try:
        from PySide6 import QtWidgets  # noqa: F401
    except Exception:
        print('SKIP cast dialog (no PySide6)')
        return
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from tp.gui_qt import _app as qt_app
    qt_app()
    from tp.gui_all import CastDialog

    class StubSvc:
        def cached(self, mal_id=None, title=None):
            return None                       # force the worker path

        def fetch(self, mal_id=None, title=None):
            return _mk_rec()

    dlg = CastDialog(StubSvc(), 41219, 'Fanren')
    import time as _t
    deadline = _t.time() + 2
    while dlg.lst.count() < 2 and _t.time() < deadline:
        dlg._drain()
        _t.sleep(0.02)
    assert dlg.lst.count() == 2, dlg.lst.count()
    assert 'Li Han' in dlg.lst.item(0).text()
    assert '韩立' in dlg.lst.item(0).text()          # native shown
    dlg.lst.setCurrentRow(0)
    html = dlg.pane.toHtml()
    assert 'Li Han' in html and 'Wenqing Qian' in html
    assert 'anilist.co/character/230157' in html       # clickable link
    dlg.done(0)
    print('PASS CastDialog renders rows + detail pane (headless)')


def main():
    test_parse()
    test_cache_first()
    test_bangumi_boost()
    test_dialog_headless()
    print('CHARACTERS OK')


if __name__ == '__main__':
    main()
