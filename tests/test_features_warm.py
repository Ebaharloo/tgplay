#!/usr/bin/env python3
"""test_features_warm - how each source prefetches the next episode's bytes.

tg/tgp/agp byte-mirror into the Prefetcher + proxy; axp/zoro pull the HLS
stream to a cache file (and fall back to the mirror for a non-direct stream,
which a direct-with-no-cache-less session never produces).
"""
import os
import sys
import tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.features import REGISTRY, get  # noqa: E402
from tp.features import warm as fw  # noqa: E402
from tp.providers.animegate import AnimeGateProvider  # noqa: E402
from tp.providers.animex import AnimeXProvider  # noqa: E402
from tp.providers.telegram import TelegramProvider, SingleFileProvider  # noqa: E402
from tp.providers.zoro import ZoroProvider  # noqa: E402


def test_registry():
    assert get('tg', 'warm') is fw.MirrorWarm
    assert get('tgp', 'warm') is fw.MirrorWarm
    assert get('agp', 'warm') is fw.MirrorWarm
    assert get('axp', 'warm') is fw.HlsWarm
    assert get('zoro', 'warm') is fw.HlsWarm
    assert REGISTRY['warm']


def test_wiring():
    assert type(TelegramProvider.warm) is fw.MirrorWarm
    assert type(SingleFileProvider.warm) is fw.MirrorWarm
    assert type(AnimeGateProvider.warm) is fw.MirrorWarm
    assert type(AnimeXProvider.warm) is fw.HlsWarm
    assert type(ZoroProvider.warm) is fw.HlsWarm


class Ctx:
    def __init__(self, proxy=None, cache=None):
        class Pf:
            def prefetch(self, name, st):
                return {'done': name}
            def publish(self, proxy, name, p):
                self.published = (proxy, name, p)
                return 1024
        self.prefetcher = Pf()
        self.proxy = proxy
        self.cache = cache
        self._swept = 0

    def _sweep_hls(self):
        self._swept += 1


class St:
    def __init__(self, direct=False, url='u', headers=None):
        self.direct = direct
        self.url = url
        self.headers = headers or {}


class Cache:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix='tgplay-warm-')

    def path(self, kind):
        return os.path.join(self.tmp, kind)


def test_mirror_uses_prefetcher_and_proxy():
    ctx = Ctx(proxy='P')
    out = fw.MirrorWarm().run(ctx, St(), 'name.mkv', 2)
    assert out is None                     # bytes live in the mirror, not disk
    assert ctx.prefetcher.published == ('P', 'name.mkv', {'done': 'name.mkv'})


def test_hls_pulls_to_disk_and_never_prefetches():
    ctx = Ctx(cache=Cache())
    st = St(direct=True, url='hls://x')
    with mock.patch('tp.features.warm.hls_to_file') as hf:
        hf.side_effect = lambda *a, **k: open(a[2], 'wb').write(b'x') or True
        out = fw.HlsWarm().run(ctx, st, 'ep-3!?.mkv', 3)
    assert out and out.endswith('.mkv')    # unsafe chars sanitized, .mkv forced
    assert hf.call_args[0][0] == 'hls://x'
    assert ctx._swept == 1
    assert not hasattr(ctx.prefetcher, 'published')  # hls never touches mirror


def test_hls_failure_returns_none_no_prefetch():
    ctx = Ctx(cache=Cache())
    with mock.patch('tp.features.warm.hls_to_file', return_value=False):
        out = fw.HlsWarm().run(ctx, St(direct=True), 'x.mkv', 4)
    assert out is None
    assert not hasattr(ctx.prefetcher, 'published')


def test_hls_non_direct_falls_back_to_mirror():
    ctx = Ctx(proxy='P', cache=Cache())
    out = fw.HlsWarm().run(ctx, St(direct=False), 'name.mkv', 5)
    assert out is None
    assert ctx.prefetcher.published[1] == 'name.mkv'


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('.', name)
    print('ok - test_features_warm')


if __name__ == '__main__':
    main()
