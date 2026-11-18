#!/usr/bin/env python3
"""test_animex - AnimeX provider parsing, audio/server selection, direct source.

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

    def _m3u8_qualities(self, url):
        return []     # no CDN request: the label stays tag-only


class FakeNoDub(Fake):
    def _json(self, u):
        if '/rest/api/servers' in u:
            return {'dubProviders': [],
                    'subProviders': [{'id': 'nero'}, {'id': 'zuna'}]}
        return super()._json(u)


def test_helpers():
    assert base_slug('https://animex.one/anime/foo-bar-123') == 'foo-bar-123'
    assert base_slug('https://animex.one/watch/foo-bar-123-episode-7') == 'foo-bar-123'
    assert base_slug('axp:foo-bar-123') == 'foo-bar-123'
    assert pretty_title('foo-bar-123') == 'Foo Bar'
    data = [{}, 'sluggy', 5]
    assert _dv(data, 1) == 'sluggy' and _dv(data, 99) == 99
    assert _find_anime({'a': [1, {'slug': 1, 'anilistId': 2}]}) == {'slug': 1, 'anilistId': 2}
    print('PASS animex helpers')


def test_catalog_and_audio():
    p = Fake()
    groups = p.fetch_groups()
    labels = [g['label'] for g in groups]
    assert labels == ['nero  (dub+sub)', 'yuki  (dub)', 'zuna  (sub)'], labels
    assert p.title.startswith('KONOSUBA'), p.title
    assert p.slug == 'konosuba-gods-blessing-on-this-wonderful-world-s4xov'
    assert p.mal_id == 30831 and p.anilist_id == 21202

    p.set_audio('dub'); p.select('nero  (dub+sub)')
    assert (p._audio, p._pid) == ('dub', 'nero'), (p._audio, p._pid)

    p.set_audio('sub'); p.select('zuna  (sub)')
    assert (p._audio, p._pid) == ('sub', 'zuna'), (p._audio, p._pid)

    # a remembered quality string (e.g. "720") -> the audio's default server
    p.set_audio('dub'); p.select('720')
    assert (p._audio, p._pid) == ('dub', 'nero')

    # a sub-only server chosen while dub -> falls back to a dub server
    p.set_audio('dub'); p.select('zuna  (sub)')
    assert p._audio == 'dub' and p._pid in ('nero', 'yuki')

    eps = p.episodes()
    assert eps[1] == 'Ep One', eps
    assert eps[2] == 'nii', eps
    print('PASS animex catalog + audio/server selection')


def test_audio_fallback_no_dub():
    p = FakeNoDub()
    p.fetch_groups()
    assert p._providers['dub'] == [] and p._providers['sub'] == ['nero', 'zuna']
    p.set_audio('dub'); p.select('nero')
    assert p._audio == 'sub' and p._pid == 'nero', (p._audio, p._pid)
    p.set_audio('auto'); p.select(None)
    print('PASS animex dub-missing fallback to sub')


def test_stream_and_rotate():
    p = Fake()
    p.fetch_groups()
    p.set_audio('dub'); p.select('nero  (dub+sub)')
    s = p.stream(1)
    assert isinstance(s, DirectSource) and s.direct
    assert s.url.endswith('master.m3u8')
    assert s.subs == []                       # dub -> no subtitle tracks
    assert p._pid == 'nero'
    assert p.rotate() is True and p._pid == 'yuki'
    assert p.rotate() is True and p._pid == 'nero'   # wraps

    p.set_audio('sub'); p.select('nero  (dub+sub)')
    s = p.stream(1)
    assert s.subs and s.subs[0][0] == 'English'      # sub -> English track
    print('PASS animex direct source + rotate')


def main():
    test_helpers()
    test_catalog_and_audio()
    test_audio_fallback_no_dub()
    test_stream_and_rotate()
    print('ANIMEX OK')


if __name__ == '__main__':
    main()


class NoDubEp(AnimeXProvider):
    """Ep 2 has no dub anywhere; ep 1 does. Mirrors a real split dub."""

    def __init__(self):
        super().__init__('https://animex.one/anime/x-1')

    def _json(self, u):
        if '/rest/api/servers' in u:
            return {'dubProviders': [{'id': 'nero'}],
                    'subProviders': [{'id': 'zuna'}]}
        if '/rest/api/episodes' in u:
            return [{'number': 1}, {'number': 2}]
        if '/rest/api/sources' in u:
            if 'type=dub' in u:
                return {'sources': []}
            return {'sources': [{'url': 'https://cdn.example/s/sub.m3u8'}],
                    'tracks': [{'lang': 'english', 'label': 'English',
                                'url': 'https://cdn.example/en.vtt'}]}
        raise AssertionError(u)

    def _probe(self, url):
        return True

    def _m3u8_qualities(self, url):
        return []


def test_missing_dub_falls_back_to_sub():
    p = NoDubEp()
    p.fetch_groups()
    p.set_audio('dub')
    p.select()
    s = p.stream(2)
    assert s.url.endswith('sub.m3u8'), s.url
    assert s.subs, 'the sub track must come along with the fallback'


class DeadDubAudio(NoDubEp):
    """The dub master answers but its audio playlist is 404: silent video."""

    def _json(self, u):
        if 'type=dub' in u:
            return {'sources': [{'url': 'https://cdn.example/s/dub.m3u8'}]}
        return super()._json(u)

    def _audio_dead(self, master_url):
        return 'dub.m3u8' in master_url


def test_dead_dub_audio_track_falls_back_to_sub():
    p = DeadDubAudio()
    p.fetch_groups()
    p.set_audio('dub')
    p.select()
    s = p.stream(2)
    assert s.url.endswith('sub.m3u8'), s.url


class _OkResp:
    def read(self, n=None):
        return b'#EXTM3U\n' if n else b'#EXTM3U\n#EXT-X-STREAM-INF:RESOLUTION=1x1\n'


class _RefHttp:
    """Media host that only answers when the referer is its own origin."""

    def __init__(self, ok):
        self.ok = ok
        self.seen = []

    def request(self, url, headers=None, method='GET', data=None):
        return {'url': url, 'headers': dict(headers or {})}

    def open(self, req, timeout=None, tries=None):
        if req['headers'].get('Referer') != self.ok:
            raise RuntimeError('403')
        return _OkResp()


def test_media_host_gets_the_referer_it_accepts_then_cached():
    p = AnimeXProvider('axp:x-1')
    p.http = _RefHttp('https://hls.dramahot.top/')
    u = 'https://hls.dramahot.top/p/x/master.m3u8'
    assert p.headers_for(u)['Referer'] == 'https://hls.dramahot.top/'
    n = len(p.http.seen)
    assert p.headers_for(u)['Referer'] == 'https://hls.dramahot.top/'
    assert len(p.http.seen) == n, 'a known host must not be re-probed'
