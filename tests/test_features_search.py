#!/usr/bin/env python3
"""test_features_search - title search per source, zoro now wired in.

search_all gathers every source through the REGISTRY (no per-source ifs in
tp/search); tg/tgp have no search. agp/axp/zoro each own their class.
"""
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.features import REGISTRY, get  # noqa: E402
from tp.features import search as fse  # noqa: E402
from tp import search as search_mod  # noqa: E402
from tp import finder as finder_mod  # noqa: E402


def test_registry():
    assert get('agp', 'search') is fse.AgpSearch
    assert get('axp', 'search') is fse.AxpSearch
    assert get('zoro', 'search') is fse.ZoroSearch
    assert REGISTRY['search'].get('tg') is None


def test_search_all_collects_every_source():
    rows = {'agp': [{'title': 'A', 'url': 'agp:a', 'source': 'agp'}],
            'axp': [{'title': 'B', 'url': 'axp:b', 'source': 'axp'}],
            'zoro': [{'title': 'C', 'url': 'zoro:c', 'source': 'zoro'}]}

    def fake_search(self, q, http=None, limit=12):
        return rows[self.kind]

    with mock.patch.object(fse.AgpSearch, 'search', fake_search), \
            mock.patch.object(fse.AxpSearch, 'search', fake_search), \
            mock.patch.object(fse.ZoroSearch, 'search', fake_search):
        got = search_mod.search_all('x')
    assert [r['url'] for r in got] == ['agp:a', 'axp:b', 'zoro:c'], got


def test_search_all_skips_unknown_sources_and_failures():
    # tg has no search; a raising source must not hide the others
    with mock.patch.object(fse.AgpSearch, 'search',
                           lambda self, q, **k: (_ for _ in ()).throw(
                               RuntimeError('down'))), \
            mock.patch.object(fse.ZoroSearch, 'search',
                              lambda self, q, **k: [{'title': 'C',
                                                     'url': 'zoro:c',
                                                     'source': 'zoro'}]):
        got = search_mod.search_all('x', sources=('agp', 'tg', 'zoro'))
    assert got == [{'title': 'C', 'url': 'zoro:c', 'source': 'zoro'}]


def test_search_all_blank():
    assert search_mod.search_all('  ') == []


def test_finder_search_one_uses_registry():
    with mock.patch.object(fse.AxpSearch, 'search',
                           lambda self, q, **k: [{'title': 'B',
                                                  'url': 'axp:b',
                                                  'source': 'axp'}]):
        got = finder_mod.ShowFinder._search_one('axp', 'B')
    assert got == [{'title': 'B', 'url': 'axp:b', 'source': 'axp'}]
    assert finder_mod.ShowFinder._search_one('tg', 'B') == []


def test_zoro_search_url_routes_back():
    class FakeProv:
        def search(self, q):
            return [('one-piece-111', 'One Piece')]

    with mock.patch('tp.providers.zoro.ZoroProvider', lambda **k: FakeProv()):
        got = fse.ZoroSearch().search('one piece')
    assert got == [{'title': 'One Piece', 'url': 'zoro:one-piece-111',
                    'source': 'zoro'}]
    from tp.cli_all import route
    assert route('zoro:one-piece-111') == ('zoro', 'zoro:one-piece-111')


def test_zoro_slug_strips_prefix():
    from tp.providers.zoro import ZoroProvider
    # real class, no network (empty target's title is derived, not fetched)
    p = ZoroProvider.__new__(ZoroProvider)
    ZoroProvider.__init__(p, 'zoro:one-piece-111')
    assert p.slug == '/one-piece-111'
    p2 = ZoroProvider.__new__(ZoroProvider)
    ZoroProvider.__init__(p2, '')
    assert p2.slug == ''


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('.', name)
    print('ok - test_features_search')


if __name__ == '__main__':
    main()
