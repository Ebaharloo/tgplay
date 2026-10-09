#!/usr/bin/env python3
"""test_search - provider search parsers + the combined search box helper."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tp.providers import animegate  # noqa: E402
from tp.providers import animex     # noqa: E402
from tp import search as searchmod  # noqa: E402


class FakeResp:
    def __init__(self, data):
        self._d = data

    def read(self, n=-1):
        return self._d

    def close(self):
        pass


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def request(self, url, headers=None, method='GET', data=None):
        self.calls.append((url, method, data))
        return (url, method, data)

    def open(self, req, timeout=None, tries=None):
        return FakeResp(self.payload)


def test_animegate_search():
    payload = json.dumps({'status': 'ok', 'types': [
        {'type': 'anime', 'items': [
            {'title': 'Kono Subarashii Sekai ni Shukufuku wo!',
             'url': 'https://animegate.ir/anime/kono-subarashii-9806'},
            {'title': '', 'url': 'https://x'}]},
        {'type': 'movie', 'items': []}]}).encode()
    http = FakeHttp(payload)
    out = animegate.search('konosuba', http=http)
    assert out == [{'title': 'Kono Subarashii Sekai ni Shukufuku wo!',
                    'url': 'https://animegate.ir/anime/kono-subarashii-9806',
                    'source': 'agp'}], out
    assert '/global-search?s=konosuba' in http.calls[0][0]
    print('PASS animegate search')


def test_animex_search():
    payload = json.dumps({'data': {'searchAnime': {'items': [
        {'id': 'konosuba-gods-blessing-on-this-wonderful-world-s4xov',
         'titleEnglish': "KONOSUBA -God's blessing", 'titleRomaji': 'Kono',
         'anilistId': 21202, 'malId': 30831}]}}}).encode()
    http = FakeHttp(payload)
    out = animex.search('konosuba', http=http)
    assert out[0]['url'] == 'axp:konosuba-gods-blessing-on-this-wonderful-world-s4xov', out
    assert out[0]['source'] == 'axp' and out[0]['malId'] == 30831, out
    assert 'graphql.animex.one' in http.calls[0][0]
    print('PASS animex search')


def test_animex_bare_slug():
    assert animex.base_slug('axp:foo-bar-x1') == 'foo-bar-x1'
    assert animex.base_slug('konosuba-gods-blessing-x') == 'konosuba-gods-blessing-x'
    try:
        animex.base_slug('https://example.com/nope')
        raise AssertionError('should reject')
    except ValueError:
        pass
    print('PASS animex bare-slug handling')


def test_search_all_sources():
    ag = lambda q, **k: [{'title': 'A', 'url': 'u1', 'source': 'agp'}]
    ax = lambda q, **k: [{'title': 'B', 'url': 'u2', 'source': 'axp'}]
    old_ag, old_ax = animegate.search, animex.search
    animegate.search, animex.search = ag, ax
    try:
        assert searchmod.search_all('x') == [{'title': 'A', 'url': 'u1', 'source': 'agp'},
                                             {'title': 'B', 'url': 'u2', 'source': 'axp'}]
        assert searchmod.search_all('x', sources=('axp',))[0]['source'] == 'axp'
        assert searchmod.search_all('  ') == []
    finally:
        animegate.search, animex.search = old_ag, old_ax
    print('PASS search_all routing')


def main():
    test_animegate_search()
    test_animex_search()
    test_animex_bare_slug()
    test_search_all_sources()
    print('SEARCH OK')


if __name__ == '__main__':
    main()
