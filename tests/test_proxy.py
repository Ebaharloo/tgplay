#!/usr/bin/env python3
"""test_proxy - the unified RangeProxy + Cache (Phase 2).

Uses an in-memory BytesSource, so no network. Run: python3 tests/test_proxy.py
"""
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from tp.cache import Cache          # noqa: E402
from tp.proxy import RangeProxy     # noqa: E402
from tp.sources import BytesSource  # noqa: E402

DATA = bytes(range(256)) * 20000    # ~5.1 MB


def _get(url, rng=None):
    req = urllib.request.Request(url)
    if rng:
        req.add_header('Range', rng)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_proxy_ranges():
    p = RangeProxy(port=0, head_b=64 * 1024, tail_b=32 * 1024).start()
    p.register('m.mkv', BytesSource(DATA))
    url = p.url('m.mkv')

    code, h, body = _get(url)  # no Range -> 200 full
    assert code == 200 and int(h['Content-Length']) == len(DATA), (code, h)
    assert body == DATA

    code, h, body = _get(url, 'bytes=100-299')
    assert code == 206 and body == DATA[100:300], (code, len(body))
    assert h['Content-Range'] == f'bytes 100-299/{len(DATA)}'

    # prewarm -> head + tail in RAM
    ev = threading.Event()
    p.prewarm('m.mkv', ev)
    assert ev.wait(5), 'prewarm did not signal'
    st = p.get('m.mkv')
    assert st.head == DATA[:64 * 1024], len(st.head)
    assert st.tail == DATA[-32 * 1024:], len(st.tail)
    assert _get(url, 'bytes=0-1023')[2] == DATA[:1024]
    n = len(DATA)
    assert _get(url, f'bytes={n - 500}-{n - 1}')[2] == DATA[-500:]

    # a gap far beyond head/tail -> live read from the source
    mid = n // 2
    assert _get(url, f'bytes={mid}-{mid + 999}')[2] == DATA[mid:mid + 1000]

    # unknown stream -> 404
    assert _get(p.url('nope.mkv'))[0] == 404
    p.stop()
    print('PASS proxy ranges + prewarm + tail + live gap')


def test_local_mirror():
    p = RangeProxy(port=0, head_b=1024, tail_b=1024).start()
    p.register('w.mkv', BytesSource(DATA), size=len(DATA))
    tmp = tempfile.mkdtemp(prefix='tgplay-mirror-')
    lo = 1000
    path = os.path.join(tmp, 'w.mkv')
    open(path, 'wb').write(DATA[lo:lo + 5000])  # window [lo, lo+5000)
    p.set_local('w.mkv', path, len(DATA), lo=lo)
    body = _get(p.url('w.mkv'), f'bytes={lo + 100}-{lo + 199}')[2]
    assert body == DATA[lo + 100:lo + 200], body[:20]
    p.stop()
    print('PASS proxy local mirror')


def test_cache():
    d = tempfile.mkdtemp(prefix='tgplay-cache-')
    c = Cache(d, budget=250)
    for name, size, age in (('a.mkv', 100, 300), ('b.mkv', 100, 200),
                            ('c.mkv', 60, 100)):
        p = c.path(name)
        open(p, 'wb').write(b'x' * size)
        os.utime(p, (age, age))
    open(c.path('b.mkv') + '.done', 'w').write('{}')
    c.set_geometry('keep.mkv', 0, 50, 50)

    c.evict(keep=(c.path('a.mkv'),))
    assert os.path.exists(c.path('a.mkv')), 'in-use file must survive'
    assert not os.path.exists(c.path('c.mkv')), 'oldest evicted first'
    assert c.is_full('keep.mkv') is True
    assert c.is_full('b.mkv') is False
    print('PASS cache eviction + geometry')


def main():
    test_proxy_ranges()
    test_local_mirror()
    test_cache()
    print('PROXY OK')


if __name__ == '__main__':
    main()
