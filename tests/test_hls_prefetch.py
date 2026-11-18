#!/usr/bin/env python3
"""HLS warming: the next episode is pulled to disk while episode 1 plays.

Needs ffmpeg (skipped otherwise). No network: the "stream" is a local m3u8.
Run: env -u PYTHONPATH .venv/bin/python -m pytest tests/test_hls_prefetch.py -q
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['AGP_NO_TRACK'] = '1'

import pytest  # noqa: E402

from tp.cache import Cache  # noqa: E402
from tp.config import Config  # noqa: E402
from tp.episodes import Episode  # noqa: E402
from tp.playlist import Playlist  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which('ffmpeg') is None
                                and shutil.which('ffmpeg') is None,
                                reason='ffmpeg not installed')


class Stream:
    direct = True

    def __init__(self, url, headers=None):
        self.url = url
        self.headers = dict(headers or {'Referer': 'https://x/'})
        self.subs = []


class Provider:
    title = 'Test Show'
    mal_id = None

    def __init__(self, url):
        self.url = url
        self.calls = []

    def stream(self, n):
        self.calls.append(n)
        return Stream(self.url)

    def display_name(self, n):
        return f'Test Show - {n}.mkv'


class Player:
    def __init__(self):
        self.urls = []

    def command(self, url, **kw):
        self.urls.append(url)
        return ['true']

    def play(self, cmd):
        return 0


class Prefetcher:                     # bytes path unused for direct streams
    def prefetch(self, *a, **k):
        return None


@pytest.fixture()
def hls(tmp_path):
    out = tmp_path / 'hls'
    out.mkdir()
    subprocess.run(
        ['ffmpeg', '-nostdin', '-loglevel', 'error', '-y',
         '-f', 'lavfi', '-i', 'testsrc=duration=6:size=64x64:rate=5',
         '-c:v', 'libx264', '-g', '5', '-f', 'hls', '-hls_time', '2',
         '-hls_playlist_type', 'vod', str(out / 'index.m3u8')], check=True)
    return str(out / 'index.m3u8')


def test_warm_pulls_hls_to_disk_and_skips_the_scrape(tmp_path, hls):
    prov = Provider(hls)
    cache = Cache(str(tmp_path / 'cache'))
    player = Player()
    pl = Playlist(prov, None, cache, player, Config(),
                  prefetcher=Prefetcher())
    pl._skip_mode, pl._skip_toggle = 'off', False

    pl._warm(Episode(2, 'ep2'))                  # what the trigger thread does

    warm = pl._pre[2]
    assert warm['path'] and os.path.exists(warm['path']), warm
    assert os.path.getsize(warm['path']) > 4096
    assert 'flags' in warm                       # probe decided (or skipped)

    prov.calls.clear()
    pl.run([Episode(2, 'ep2')], skip_mode='off', cut=None)

    assert player.urls and player.urls[0] == warm['path'], player.urls
    assert prov.calls == []                      # no re-scrape, no re-probe
    assert 2 not in pl._pre                      # consumed once


def test_warm_falls_back_to_the_stream_when_download_fails(tmp_path):
    prov = Provider(str(tmp_path / 'missing.m3u8'))
    cache = Cache(str(tmp_path / 'cache'))
    player = Player()
    pl = Playlist(prov, None, cache, player, Config(),
                  prefetcher=Prefetcher())
    pl._skip_mode, pl._skip_toggle = 'off', False

    pl._warm(Episode(2, 'ep2'))
    warm = pl._pre[2]
    assert warm['path'] is None                  # ffmpeg refused

    prov.calls.clear()
    pl.run([Episode(2, 'ep2')], skip_mode='off', cut=None)
    assert prov.calls == [2]                     # normal path still works
    assert player.urls[0].startswith('file://') or 'missing' in player.urls[0]
