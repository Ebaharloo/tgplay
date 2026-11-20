#!/usr/bin/env python3
"""test_agp_single_link - a direct /download/ URL opens as one AGP episode."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.providers.animegate import AnimeGateProvider        # noqa: E402

URL = ('https://host2.gate-server-1.ir/download/x9/token='
       '/anime-21781-4-337/20261122/ONA/2026/Jiyi%20Guanli%20Ju%202026/'
       'hardsub/720/%5B@AnimeGateOfficial%5D%20Jiyi%20Guanli%20Ju%202026'
       '%20-%20(4).mkv')


def _p():
    return AnimeGateProvider(URL, cookies={'animegate_mr_session': 'x'})


def test_download_url_becomes_one_episode():
    p = _p()
    assert p.single and p._loaded
    assert p.title == 'Jiyi Guanli Ju 2026 - (4).mkv', p.title
    eps = p.episodes()
    assert eps == {1: p.title}
    p.load()                                    # no network, no crash


def test_stream_returns_the_given_url():
    src = _p().stream(1)
    assert src.url == URL
    assert 'Referer' in src.headers             # agp CDN needs the referer


if __name__ == '__main__':
    for n, f in sorted(globals().items()):
        if n.startswith('test_'):
            f()
            print('ok', n)
