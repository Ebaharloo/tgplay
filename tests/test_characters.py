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


class NoFandom:
    """No wiki lookups in unit tests (they'd hit the network)."""
    def fetch(self, titles):
        return []

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
    rows = ch._rows_from_media(MEDIA, "anime")
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
            'rows': ch._rows_from_media(MEDIA, "anime")}


def test_cache_first():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-cast-')).ensure()
    svc = ch.CharactersService(cfg, http=None, fandom=NoFandom())

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

    svc = ch.CharactersService(cfg, http=None, fandom=NoFandom(), bangumi=FakeBgm())
    svc._anilist = lambda mal_id, title: _mk_rec()
    rec = svc.fetch(mal_id=41219)
    names = [r['name'] for r in rec['rows']]
    assert '韩立' in names and rec.get('has_cn'), names   # CN row merged
    assert any(r['va'] == 'Yuanjiang Bao' for r in rec['rows'])
    print('PASS Bangumi boost merges CN characters + CN voice actors')


def test_dialog_headless():
    """CastDialog is pure widget code: build it with a stub service, deliver
    a rec through the worker queue and check rows + detail pane render."""
    from PySide6 import QtWidgets  # noqa: F401
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
    # search filters the list live
    dlg.search.setText('nan gong')
    assert dlg.lst.count() == 1, dlg.lst.count()
    assert 'Nan Gong' in dlg.lst.item(0).text()
    dlg.search.setText('')
    assert dlg.lst.count() == 2, dlg.lst.count()
    # source filter: filling a source still keeps the anime's MAIN cast
    dlg.origin_cb.setCurrentText('Novel')
    assert dlg.lst.count() == 1 and 'Li Han' in dlg.lst.item(0).text(), \
        dlg.lst.count()
    dlg.origin_cb.setCurrentText('All')
    assert dlg.lst.count() == 2, dlg.lst.count()
    # Fandom images need the wiki Referer (Cloudflare 403s otherwise)
    assert CastDialog._referer_for(
        {'from': 'wiki', 'wiki': 'xian-ni'}) == 'https://xian-ni.fandom.com/'
    assert CastDialog._referer_for({'from': 'anime'}) == 'https://anilist.co/'
    dlg.done(0)
    print('PASS CastDialog renders rows + detail pane + search/source filter')


def test_pagination_and_source_material():
    """ALL anime pages are fetched, and the manga/novel relation's cast is
    merged in (tagged 'novel'), with duplicates dropped (anime wins)."""
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-cast-')).ensure()
    svc = ch.CharactersService(cfg, http=None, fandom=NoFandom())

    def row(cid, name, native=''):
        return {'role': 'SUPPORTING', 'voiceActors': [],
                'node': {'id': cid, 'name': {'full': name, 'native': native},
                         'image': {}, 'favourites': 0, 'description': '',
                         'siteUrl': ''}}

    def fake_gql(query, variables):
        if query is ch.RELATIONS_QUERY:
            # the anime does NOT link its novel (the real Renegade case)
            return {'Media': {'id': 900, 'relations': {'edges': []}}}
        if query is ch.SEARCH_SOURCE_QUERY:
            return {'Page': {'media': [
                {'id': 501, 'type': 'MANGA', 'format': 'NOVEL',
                 'title': {'romaji': 'Xian Ni'}}]}}
        if variables.get('id'):                 # the novel's cast
            return {'Media': {'id': 501, 'type': 'MANGA', 'format': 'NOVEL',
                              'title': {'romaji': 'Xian Ni'},
                              'characters': {'pageInfo': {'hasNextPage': False},
                                             'edges': [
                     row(7001, 'Wang Lin', '王林'),
                     row(230157, 'Li Han')]}}}  # duplicate -> anime wins
        page = int(variables.get('page') or 1)  # anime pages
        return {'Media': {
            'id': 115844, 'idMal': 41219, 'title': {'romaji': 'Xian Ni'},
            'characters': {
                'pageInfo': {'hasNextPage': page == 1},
                'edges': [row(230157, 'Li Han', '韩立') if page == 1
                          else row(3002, 'Situ Nan')]}}}

    svc._gql = fake_gql
    rec = svc.fetch(mal_id=41219)
    names = [r['name'] for r in rec['rows']]
    assert 'Li Han' in names and 'Situ Nan' in names, names   # both pages
    assert 'Wang Lin' in names, names                         # novel merged
    assert names.count('Li Han') == 1, names                  # deduped
    origins = {r['name']: r['from'] for r in rec['rows']}
    assert origins['Wang Lin'] == 'novel' and origins['Li Han'] == 'anime'
    assert len(rec['rows']) == 3, rec['rows']
    assert svc.cached(mal_id=41219), 'merged cast must be cached'
    print('PASS paginated anime cast + manga/novel merge + dedupe')


def test_wiki_merge():
    """Fandom wiki rows are merged in (deduped by name), tagged 'wiki'."""
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-cast-')).ensure()
    svc = ch.CharactersService(cfg, http=None)

    class FakeFandom:
        def fetch(self, titles):
            return [
                {'cid': 'fandom:xian-ni/Wang Lin', 'name': 'Wang Lin',
                 'native': '', 'role': '', 'image': '', 'fav': 0, 'desc': '',
                 'url': 'https://xian-ni.fandom.com/wiki/Wang_Lin',
                 'va': '', 'va_lang': '', 'from': 'wiki', 'wiki': 'xian-ni'},
                {'cid': 'fandom:xian-ni/Li Han', 'name': 'Li Han',
                 'native': '', 'role': '', 'image': '', 'fav': 0, 'desc': '',
                 'url': '', 'va': '', 'va_lang': '', 'from': 'wiki',
                 'wiki': 'xian-ni'},
            ]

    svc.fandom = FakeFandom()
    svc._anilist = lambda mal_id, title: _mk_rec()
    rec = svc.fetch(mal_id=41219)
    names = [r['name'] for r in rec['rows']]
    assert 'Wang Lin' in names and rec.get('has_wiki'), names
    assert names.count('Li Han') == 1, names     # AniList row wins the dupe
    assert rec.get('wiki') == 'xian-ni', rec
    print('PASS Fandom wiki merged (dedupe keeps the AniList row)')


def main():
    test_parse()
    test_cache_first()
    test_bangumi_boost()
    test_pagination_and_source_material()
    test_wiki_merge()
    test_dialog_headless()
    print('CHARACTERS OK')


if __name__ == '__main__':
    main()
