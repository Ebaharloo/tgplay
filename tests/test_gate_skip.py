#!/usr/bin/env python3
"""Gate tests: independent of the implementer's suite (skip refactor 258e3a8).

Claims under test:
  1. a dead/failing ffprobe binary must not stop the next candidate
  2. probe_targets() is the whole candidate contract: direct HLS with headers,
     proxied stream, same URL not duplicated, nothing to probe
  3. both candidates empty -> ani-skip fallback note
  4. warm path must hand the probe a proxy URL that proxy can actually serve

Run: env -u PYTHONPATH .venv/bin/python -m pytest tests/test_gate_skip.py -q
No network, no mpv, no ffprobe.
"""
import os
import sys
import types
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tp.chapters import ChapterReader  # noqa: E402
from tp.episodes import Episode  # noqa: E402
from tp.features.warm import MirrorWarm  # noqa: E402
from tp.playlist import Playlist  # noqa: E402
from tp.proxy import RangeProxy  # noqa: E402
from tp.skip import SkipDecider, SkipService, probe_targets  # noqa: E402
from tp.sources import DirectSource, HttpSource  # noqa: E402

CHS = [('Intro', 0.0, 90.0), ('Episode', 90.0, 1200.0),
       ('Ending', 1200.0, 1260.0)]


class Ani:
    def __init__(self, flags): self._f = flags
    def available(self): return True
    def flags(self, mal, ep, toggle=False): return list(self._f)


class Meta:
    def resolve_mal(self, title, ask=False): return 7


# --- 1. failing reader -----------------------------------------------------
def test_dead_ffprobe_binary_still_tries_the_proxy_candidate():
    """Real ChapterReader + a binary that does not exist: it fails, returns [],
    and SkipService must go on to the proxy candidate."""
    dead = ChapterReader(ffprobe='/nonexistent/ffprobe-gate')
    assert dead.read('https://cdn.example/x.mkv') == []      # OSError swallowed
    calls = []

    class Reader:
        def read(self, url, headers=None, timeout=None):
            calls.append(url)
            if url.startswith('http://127.0.0.1'):
                return list(CHS)
            return dead.read(url, headers=headers, timeout=timeout)

    svc = SkipService(reader=Reader(), ani_skip=Ani([]))
    flags, note = svc.flags(title='T', ep=1, timeout=1, targets=[
        ('https://cdn.example/x.mkv', {'Referer': 'r'}),
        ('http://127.0.0.1:9/x.mkv', None)])
    assert flags, (flags, note)
    assert note.startswith('chapters(named)'), note
    assert calls == ['https://cdn.example/x.mkv', 'http://127.0.0.1:9/x.mkv']


def test_raising_reader_still_tries_the_proxy_candidate():
    """A reader that throws (not just returns []) must not stop the walk."""
    calls = []

    class Boom:
        def read(self, url, headers=None, timeout=None):
            calls.append(url)
            if url.startswith('http://127.0.0.1'):
                return list(CHS)
            raise RuntimeError('boom')

    flags, note = SkipService(reader=Boom(), ani_skip=Ani([])).flags(
        title='T', ep=1, targets=[('https://cdn.example/x.mkv', None),
                                  ('http://127.0.0.1:9/x.mkv', None)])
    assert flags and note.startswith('chapters(named)'), (flags, note)
    assert len(calls) == 2, calls


# --- 2. candidate contract -------------------------------------------------
def test_probe_targets_direct_hls_stream_with_headers():
    st = DirectSource('https://cdn.example/hls/index.m3u8',
                      headers={'Referer': 'https://site/', 'User-Agent': 'ua'})
    assert st.direct is True
    assert probe_targets(st) == [
        (st.url, {'Referer': 'https://site/', 'User-Agent': 'ua'})]
    assert probe_targets(st, None) == [(st.url, st.headers)]
    # no headers at all -> None, not {}
    assert probe_targets(DirectSource('https://cdn.example/v.mp4')) == [
        ('https://cdn.example/v.mp4', None)]


def test_probe_targets_proxied_stream_is_origin_then_proxy():
    st = HttpSource('https://cdn.example/x/1.mkv', headers={'Referer': 'r'})
    proxy = RangeProxy(port=18899)
    url = proxy.url('1.mkv')
    assert probe_targets(st, url) == [(st.url, {'Referer': 'r'}), (url, None)]
    assert probe_targets(None, url) == []                 # prefetched local file
    # identical URL is not probed twice
    same = DirectSource('http://127.0.0.1:9/same.m3u8')
    assert probe_targets(same, same.url) == [(same.url, None)]


# --- 3. adversarial: nothing anywhere --------------------------------------
def test_both_candidates_empty_falls_back_to_ani_skip():
    calls = []

    class Empty:
        def read(self, url, headers=None, timeout=None):
            calls.append(url)
            return []

    ani = ['--script-opts=skip-op_start=5.0,skip-op_end=95.0']
    flags, note = SkipService(reader=Empty(), ani_skip=Ani(ani),
                              metadata=Meta()).flags(
        title='T', ep=3, targets=[('https://cdn.example/x.mkv', None),
                                  ('http://127.0.0.1:9/x.mkv', None)])
    assert len(calls) == 2, calls
    assert flags == ani, flags
    assert note == 'ani-skip · op 0:05-1:35', note


def test_both_candidates_empty_and_no_ani_skip_data():
    class Empty:
        def read(self, url, headers=None, timeout=None): return []

    flags, note = SkipService(reader=Empty(), ani_skip=Ani([]),
                              metadata=Meta()).flags(
        title='T', ep=3, targets=[('https://cdn.example/x.mkv', None)])
    assert flags == [] and note == 'none (ani-skip has no data)', (flags, note)


# --- 4. warm path: proxy candidate must be servable ------------------------
def test_warm_path_proxy_candidate_is_registered_with_the_proxy():
    """_warm hands SkipService proxy.url(name). The proxy answers /f/<name>
    with 404 unless something registered that name first, so the fallback
    candidate is dead exactly when the origin hides its chapters."""
    proxy = RangeProxy(port=18899)
    st = HttpSource('https://cdn.example/x/2.mkv', headers={'Referer': 'r'})
    prov = types.SimpleNamespace(title='T', mal_id=None,
                                 stream=lambda n: st,
                                 display_name=lambda n: 'ep2.mkv',
                                 warm=MirrorWarm())
    seen = []

    def read(url, headers=None, timeout=None):
        seen.append(url)
        return []

    pl = Playlist(prov, proxy, None, None, types.SimpleNamespace(),
                  skip=SkipService(reader=types.SimpleNamespace(read=read),
                                   ani_skip=Ani([])),
                  prefetcher=types.SimpleNamespace(
                      prefetch=lambda name, s: None))
    pl._skip_mode, pl._skip_toggle = 'all', False
    pl._warm(Episode(2, 'l2'))

    assert seen and seen[0] == st.url, seen
    fallback = [u for u in seen if u.startswith('http://127.0.0.1')]
    assert fallback, f'warm path probed no proxy URL: {seen}'
    expected = urllib.parse.unquote(
        [u for u in seen if u.startswith('http://127.0.0.1')][-1]
        .split('/f/')[-1])
    assert proxy.get(expected) is not None, (
        f'_warm probed {fallback[0]} but the proxy has no stream registered '
        'under that name: that candidate can only 404')


def test_decider_named_beats_positional():
    op, ed, osrc, esrc = SkipDecider.decide(CHS, 'all')
    assert (op, ed, osrc, esrc) == ((0.0, 90.0), (1200.0, 1260.0),
                                    'named', 'named')
    op, ed, osrc, esrc = SkipDecider.decide(CHS, 'names')
    assert (osrc, esrc) == ('named', 'named')
    # unnamed short leading chapter -> positional op
    ch = [('Chapter 1', 0.0, 20.0), ('main', 20.0, 1200.0),
          ('Chapter 3', 1200.0, 1260.0)]
    op, ed, osrc, esrc = SkipDecider.decide(ch, 'all')
    assert (osrc, esrc) == ('positional', 'positional'), (op, ed, osrc, esrc)
