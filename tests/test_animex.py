#!/usr/bin/env python3
"""test_animex - AnimeX provider parsing, group/audio selection, direct source.

Network-free: a fake backend returns canned JSON in the exact shapes observed.
Run: .venv/bin/python tests/test_animex.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tp.providers.animex import (  # noqa: E402
    AnimeXProvider, base_slug, pretty_title, _dv, _find_anime)
from tp.sources import DirectSource  # noqa: E402


class Fake(AnimeXProvider):
    def __init__(self, url='https://animex.one/anime/konosuba-god-s-blessing-on-this-wonderful-world-21202'):
        super().__init__(url)

    def _json(self, u):
        if '__data.json' in u:
            return {'nodes': [None, {'data': [
                {'slug': 1, 'anilistId': 2, 'malId': 3, 'titleEnglish': 4},
                'konosuba-gods-blessing-on-this-wonderful-world-s4xov',
                21202, 30831, 'KONOSUBA -God\'s blessing']}]}
        if '/rest/api/servers' in u:
            return {'dubProviders': [{'id': 'nero', 'default': True, 'tip': 'Fast'},
                                     {'id': 'yuki', 'default': False, 'tip': 'Good'}],
                    'subProviders': [{'id': 'nero'}, {'id': 'zuna'}]}
        if '/rest/api/episodes' in u:
            return [{'number': 1, 'titles': {'en': 'Ep One'}},
                    {'number': 2, 'titles': {'ja': 'nii'}}]
        if '/rest/api/sources' in u:
            return {'sources': [{'url': 'https://cdn.example/x/master.m3u8'}],
                    'tracks': [{'lang': 'english', 'label': 'English',
                                'url': 'https://cdn.example/en.vtt'}]}
        raise AssertionError(u)

    def _probe(self, url):
        return True   # accept everything in the test


def test_helpers():
    assert base_slug('https://animex.one/anime/foo-bar-123') == 'foo-bar-123'
    assert base_slug('https://animex.one/watch/foo-bar-123-episode-7') == 'foo-bar-123'
    assert pretty_title('foo-bar-123') == 'Foo Bar'
    data = [{}, 'sluggy', 5]
    assert _dv(data, 1) == 'sluggy' and _dv(data, 99) == 99
    assert _find_anime({'a': [1, {'slug': 1, 'anilistId': 2}]}) == {'slug': 1, 'anilistId': 2}
    print('PASS animex helpers')


def test_catalog_and_audio():
    p = Fake()
    groups = p.fetch_groups()
    labels = [g['label'] for g in groups]
    assert labels == ['DUB · nero', 'DUB · yuki', 'SUB · nero', 'SUB · zuna'], labels
    assert p.title.startswith('KONOSUBA'), p.title
    assert p.slug == 'konosuba-gods-blessing-on-this-wonderful-world-s4xov'
    assert p.mal_id == 30831 and p.anilist_id == 21202

    # default -> dub, first provider
    p.select('DUB')
    assert (p._audio, p._pid) == ('dub', 'nero'), (p._audio, p._pid)
    # explicit label
    p.select('SUB · zuna')
    assert (p._audio, p._pid) == ('sub', 'zuna')
    # a non-animex quality string (remembered from ui.json) falls back safely
    p.select('720')
    assert p._audio == 'dub'

    eps = p.episodes()
    assert eps[1] == 'Ep One', eps
    assert eps[2] == 'nii', eps
    print('PASS animex catalog + audio selection')


def test_stream_and_rotate():
    p = Fake()
    p.fetch_groups()
    p.select('DUB · nero')
    s = p.stream(1)
    assert isinstance(s, DirectSource) and s.direct
    assert s.url.endswith('master.m3u8')
    assert s.subs == []                       # dub -> no subtitle tracks
    assert p._pid == 'nero'
    assert p.rotate() is True and p._pid == 'yuki'
    assert p.rotate() is True and p._pid == 'nero'   # wraps

    p.select('SUB · nero')
    s = p.stream(1)
    assert s.subs and s.subs[0][0] == 'English'      # sub -> English track
    print('PASS animex direct source + rotate')


def main():
    test_helpers()
    test_catalog_and_audio()
    test_stream_and_rotate()
    print('ANIMEX OK')


if __name__ == '__main__':
    main()
