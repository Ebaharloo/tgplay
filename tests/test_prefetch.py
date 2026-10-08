#!/usr/bin/env python3
"""test_prefetch - background mirroring into the Cache + cancellation."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.cache import Cache          # noqa: E402
from tp.prefetch import Prefetcher  # noqa: E402
from tp.sources import BytesSource  # noqa: E402

DATA = bytes(range(256)) * 20000  # ~5.1 MB


def test_full():
    d = tempfile.mkdtemp(prefix='tgplay-pf-')
    c = Cache(d, budget=10 ** 9)
    pf = Prefetcher(c)
    path = pf.prefetch('m.mkv', BytesSource(DATA))
    assert path is not None and open(path, 'rb').read() == DATA
    assert c.is_full('m.mkv') and pf.complete('m.mkv')
    assert pf.prefetch('m.mkv', BytesSource(DATA)) == path  # idempotent
    print('PASS prefetch full + complete')


def test_window():
    d = tempfile.mkdtemp(prefix='tgplay-pf-')
    c = Cache(d, budget=10 ** 9)
    pf = Prefetcher(c)
    big = DATA * 4  # ~20MB so the +/-8MB head/tail padding keeps lo>0
    path = pf.prefetch('w.mkv', BytesSource(big), lo_f=0.5, hi_f=1.0)
    assert path is not None
    g = c.geometry('w.mkv')
    assert g and g['lo'] > 0 and g['len'] < g['size'], g
    assert not c.is_full('w.mkv')  # windowed: not a whole-file mirror
    print('PASS prefetch window geometry')


def test_cancel():
    d = tempfile.mkdtemp(prefix='tgplay-pf-')
    c = Cache(d, budget=10 ** 9)
    pf = Prefetcher(c)
    pf.cancel('x.mkv')
    assert pf.prefetch('x.mkv', BytesSource(DATA)) is None
    assert not c.is_full('x.mkv')
    print('PASS prefetch cancel')


def main():
    test_full()
    test_window()
    test_cancel()
    print('PREFETCH OK')


if __name__ == '__main__':
    main()
