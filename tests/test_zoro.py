#!/usr/bin/env python3
"""test_zoro - HiAnime provider: payload decode, servers, stream fallback.

Network-free: canned responses in the exact shapes the live site returned.
Run: env -u PYTHONPATH .venv/bin/python -m pytest tests/test_zoro.py -q
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tp.providers.zoro import XOR_KEY, ZoroProvider, open_payload  # noqa: E402


def seal(obj) -> str:
    """The site's own encoding of a player payload."""
    raw = json.dumps(obj).encode('utf-8')
    return base64.b64encode(bytes(
        b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(raw))).decode()


def embed_url(host, num, audio):
    return f'https://{host}/stream/mal/61967/{num}/{audio}'


class Fake(ZoroProvider):
    """Serves the pages the live chain needed, for ep 4."""

    def __init__(self, target='', audio='dub', dead_first=False):
        super().__init__(target, audio=audio)
        self.dead_first = dead_first

    def _get(self, url, ref=''):
        if url.startswith('https://hianime.fm/search?keyword='):
            return ('<a href="/watch/black-clover-season-2-1-10492" '
                    'title="Black Clover Season 2">x</a>'
                    '<a href="https://hianime.fm/watch/other-1-9" title="Other">y</a>')
        if '/api/theme/episode/list/' in url:
            html = ''.join(
                f'<a class="ssl-item ep-item" data-number="{n}" data-id="{149955 + n}">'
                for n in (1, 2, 3, 4))
            return json.dumps({'status': True, 'totalItems': 4, 'html': html})
        if '/api/theme/episode/servers?episodeId=' in url:
            rows = ''
            for audio in ('sub', 'dub'):
                for host in ('zokoanime.video', 'megaplay.buzz'):
                    h = base64.b64encode(
                        embed_url(host, 4, audio).encode()).decode()
                    rows += (f'<div class="item server-item" data-type="{audio}" '
                             f'data-server-name="{host}" data-hash="{h}">')
            return json.dumps({'status': True, 'html': rows})
        if '/stream/mal/' in url:
            if self.dead_first and 'zokoanime' in url:
                raise OSError('403 from a dead server')
            return ('<script>window.__P="%s";</script>' % seal({
                'src': 'https://hls.example/master.m3u8',
                'subtitles': [{'lang': 'en', 'label': 'English',
                               'src': 'https://hls.example/en.vtt'}]}))
        raise AssertionError(url)


def test_payload_round_trip():
    data = {'src': 'https://hls.example/m.m3u8', 'subtitles': []}
    assert open_payload(seal(data)) == data


def test_search_and_episode_ids():
    p = Fake()
    assert [s for s, _ in p.search('black clover season 2')] == [
        '/watch/black-clover-season-2-1-10492', '/watch/other-1-9']
    assert p.episode_ids('/watch/black-clover-season-2-1-10492') == {
        1: 149956, 2: 149957, 3: 149958, 4: 149959}


def test_stream_returns_direct_source_with_subs():
    s = Fake('/watch/black-clover-season-2-1-10492', audio='dub').stream(4)
    assert s.direct and s.url == 'https://hls.example/master.m3u8'
    assert s.headers['Referer'] == 'https://zokoanime.video/'
    assert s.subs == [('English', 'https://hls.example/en.vtt')]


def test_a_dead_server_falls_through_to_the_next_one():
    s = Fake('/watch/black-clover-season-2-1-10492', audio='sub',
             dead_first=True).stream(4)
    assert s.url == 'https://hls.example/master.m3u8'


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
