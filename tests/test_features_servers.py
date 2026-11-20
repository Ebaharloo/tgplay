#!/usr/bin/env python3
"""test_features_servers - server-selection policy per source.

TgServers must NOT re-select at play time (a narrowed Telegram view would
renumber); agp/axp/zoro must. axp and zoro each own their own class.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.features import REGISTRY, get  # noqa: E402
from tp.features import servers as fs  # noqa: E402
from tp.providers.animegate import AnimeGateProvider  # noqa: E402
from tp.providers.animex import AnimeXProvider  # noqa: E402
from tp.providers.telegram import SingleFileProvider, TelegramProvider  # noqa: E402
from tp.providers.zoro import ZoroProvider  # noqa: E402


class _Rot:
    class rotate:
        pass


def test_registry():
    assert get('tg', 'servers') is fs.TgServers
    assert get('tgp', 'servers') is fs.TgServers
    assert get('agp', 'servers') is fs.AgpServers
    assert get('axp', 'servers') is fs.AxpServers
    assert get('zoro', 'servers') is fs.ZoroServers
    assert REGISTRY['servers']


def test_reselect_flags_per_source():
    assert fs.TgServers().reselects is False      # would renumber the view
    for cls in (fs.AgpServers, fs.AxpServers, fs.ZoroServers):
        assert cls().reselects is True, cls
    # the real providers carry their own objects (never a shared default)
    assert type(TelegramProvider.servers) is fs.TgServers
    assert type(SingleFileProvider.servers) is fs.TgServers
    assert type(AnimeGateProvider.servers) is fs.AgpServers
    assert type(AnimeXProvider.servers) is fs.AxpServers
    assert type(ZoroProvider.servers) is fs.ZoroServers


def test_rotate_delegates_to_provider():
    class P:
        calls = []

        def rotate(self):
            P.calls.append(1)
            return True

    assert fs.AxpServers().rotate(P()) is True and len(P.calls) == 1

    class Q:
        pass                        # no rotate: nothing to do

    assert fs.ZoroServers().rotate(Q()) is False


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('.', name)
    print('ok - test_features_servers')


if __name__ == '__main__':
    main()
