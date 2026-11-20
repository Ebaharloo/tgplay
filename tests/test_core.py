#!/usr/bin/env python3
"""test_core - the pure Phase-1 core: config, http, chapters, episodes.

Stdlib only. Run: python3 tests/test_core.py
"""
import os
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from tp import config, episodes, http, skip  # noqa: E402

DATA = bytes(range(256)) * 20000  # ~5.1 MB (exercises the parallel chunk path)


# --- http -------------------------------------------------------------------
class _H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def do_GET(self):
        rng = self.headers.get('Range')
        s, e = 0, len(DATA) - 1
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)', rng)
            if m:
                s = int(m.group(1)) if m.group(1) else 0
                e = int(m.group(2)) if m.group(2) else len(DATA) - 1
        e = min(e, len(DATA) - 1)
        body = DATA[s:e + 1]
        self.send_response(206 if rng else 200)
        if rng:
            self.send_header('Content-Range', f'bytes {s}-{e}/{len(DATA)}')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()
        self.wfile.write(body)


def test_http():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{srv.server_address[1]}/f'
    c = http.HttpClient(retries=2, backoff=0.05)
    assert c.range_bytes(url, {}, 100, 300) == DATA[100:300]
    assert c.range_bytes(url, {}, 0, 0) == b''
    # multi-connection chunk across the 1MB boundary
    assert c.chunk(url, {}, 5000, len(DATA)) == DATA[5000:]
    srv.shutdown()
    print('PASS http range + chunk')


def test_http_retry():
    import tp.http as m
    calls = {'n': 0}
    real = m.urllib.request.urlopen

    class R:
        def read(self, n=-1):
            return b''

        def close(self):
            pass

    def fake(req, timeout=None):
        calls['n'] += 1
        if calls['n'] == 1:
            raise OSError('transient blip')
        return R()

    m.urllib.request.urlopen = fake
    try:
        c = http.HttpClient(retries=3, backoff=0.01)
        c.open(c.request('http://x'))
        assert calls['n'] == 2, calls
        # an HTTP status error is NOT retried
        calls['n'] = 0
        import urllib.error

        def fake_403(req, timeout=None):
            calls['n'] += 1
            raise urllib.error.HTTPError('http://x', 403, 'no', {}, None)

        m.urllib.request.urlopen = fake_403
        try:
            c.open(c.request('http://x'))
            raise AssertionError('HTTPError should propagate')
        except urllib.error.HTTPError:
            pass
        assert calls['n'] == 1, calls
    finally:
        m.urllib.request.urlopen = real
    print('PASS http retry rules')


# --- chapters ---------------------------------------------------------------
def test_chapters():
    K = skip.SkipDecider.kind
    assert K('Intro') == 'op' and K('Opening') == 'op' and K('OP1') == 'op'
    assert K('Credits') == 'ed' and K('Ending') == 'ed' and K('Outro') == 'ed'
    assert K('Episode') is None and K('Part A') is None and K(None) is None

    donghua = [('Chapter 1', 0.0, 162.667), ('Episode Sixty', 162.667, 1198.2),
               ('Ending Song', 1198.2, 1300.667)]
    S = skip.SkipDecider.to_skip
    assert S(donghua) == ((0.0, 162.667), (1198.2, 1300.667))
    assert S(donghua, 'names') == (None, (1198.2, 1300.667))
    assert S(donghua, 'auto') == ((0.0, 162.667), (1198.2, 1300.667))

    # named beats positional; Part A/B untouched; 180s cap only for the guess
    assert S([('Chapter 1', 0, 30), ('Intro', 30, 120), ('Episode', 120, 1200),
              ('Credits', 1200, 1260)]) == ((30, 120), (1200, 1260))
    assert S([('Part A', 0, 600), ('Part B', 600, 1200)]) == (None, None)
    assert S([('Chapter 1', 0, 300), ('Episode', 300, 2400),
              ('Chapter 4', 2400, 2500)]) == (None, (2400, 2500))

    opts = skip.SkipDecider.opts_from((0.0, 162.667), (1198.2, 1300.667),
                                      toggle=True)
    assert opts == ['--script-opts=skip-op_start=0.0,skip-op_end=162.667,'
                    'skip-ed_start=1198.2,skip-ed_end=1300.667,'
                    'skip-toggle=yes,skip-toggle_key=T'], opts
    assert skip.SkipDecider.opts_from(None, None) == []
    print('PASS chapters')


def test_chapters_flags():
    # pure decide -> opts, no file read
    d = skip.SkipDecider
    chs = [('Intro', 0.0, 90.0), ('Episode', 90.0, 1300.0)]
    assert d.opts_from(*d.to_skip(chs)) == [
        '--script-opts=skip-op_start=0.0,skip-op_end=90.0']
    print('PASS chapters.flags')


# --- episodes ---------------------------------------------------------------
def test_episodes():
    eps = {1: 'L1', 2: 'L2', 3: 'L3', 10: 'L10'}
    assert episodes.parse_range('2-3,10') == [2, 3, 10]
    assert episodes.parse_range('x') == []
    assert episodes.select(eps, all=True) == [
        (1, 'L1'), (2, 'L2'), (3, 'L3'), (10, 'L10')]
    assert episodes.select(eps, nums={2, 3}) == [(2, 'L2'), (3, 'L3')]
    assert episodes.select(eps) == []
    planned = episodes.resume(eps, 2)
    assert planned == [(2, 'L2'), (3, 'L3'), (10, 'L10')]
    # every entry is a (num, link) tuple -> play()'s `num, link = e` is safe
    assert all(isinstance(e, tuple) and len(e) == 2 for e in planned)
    n, link = planned[0]
    assert (n, link) == (2, 'L2')
    print('PASS episodes')


# --- config -----------------------------------------------------------------
def test_config():
    d = tempfile.mkdtemp(prefix='tgplay-')
    c = config.Config(home=d, cache_dir=os.path.join(d, 'cache'),
                      proxy_port=1234)
    assert c.progress.endswith('/.config/tgp/progress.json')
    assert c.cache_path('a b.mkv').endswith('/a_b.mkv')
    c.ensure()
    assert os.path.isdir(c.conf) and os.path.isdir(c.cache_dir)
    assert c.proxy_port == 1234
    print('PASS config')


def main():
    test_config()
    test_http()
    test_http_retry()
    test_chapters()
    test_chapters_flags()
    test_episodes()
    print('CORE OK')


if __name__ == '__main__':
    main()
