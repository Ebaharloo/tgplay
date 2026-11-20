#!/usr/bin/env python3
"""test_features_sizes - file-size knowledge per source.

tg/tgp know the size from the message document; agp probes the signed CDN
once. axp/zoro are HLS: NoSizes - the GUI never probes them (their Size
column is '—').
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.features import REGISTRY, get  # noqa: E402
from tp.features import sizes as fsz  # noqa: E402
from tp.providers.animegate import AnimeGateProvider  # noqa: E402
from tp.providers.animex import AnimeXProvider  # noqa: E402
from tp.providers.telegram import TelegramProvider  # noqa: E402
from tp.providers.zoro import ZoroProvider  # noqa: E402


def test_registry():
    assert get('tg', 'sizes') is fsz.TgSizes
    assert get('tgp', 'sizes') is fsz.TgSizes
    assert get('agp', 'sizes') is fsz.AgpSizes
    assert get('axp', 'sizes') is None
    assert get('zoro', 'sizes') is None
    assert REGISTRY['sizes']


def test_wiring():
    assert type(TelegramProvider.sizes) is fsz.TgSizes
    assert type(AnimeGateProvider.sizes) is fsz.AgpSizes
    assert type(AnimeXProvider.sizes) is fsz.NoSizes
    assert type(ZoroProvider.sizes) is fsz.NoSizes
    assert fsz.TgSizes().capable and fsz.AgpSizes().capable
    assert not fsz.NoSizes().capable


def test_size_delegates_to_provider():
    class P:
        def size(self, n):
            return 42 if n == 2 else 0

    assert fsz.AgpSizes().size(P(), 2) == 42
    assert fsz.TgSizes().size(P(), 1) == 0


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('.', name)
    print('ok - test_features_sizes')


if __name__ == '__main__':
    main()
