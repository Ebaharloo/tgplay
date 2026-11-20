#!/usr/bin/env python3
"""test_features_auth - cookie/header/referer knowledge per source.

agp owns the Firefox-cookie health + dead markers + site referer; axp owns
the per-host media-header cache + megaplay referer; zoro's streams carry
their own embed-origin referer; tg is a Telethon session (no HTTP at all).
"""
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from tp.features import REGISTRY, get  # noqa: E402
from tp.features import auth as fa  # noqa: E402
from tp.providers.animegate import AnimeGateProvider, BASE  # noqa: E402
from tp.providers.animex import AnimeXProvider, MEDIA_REFERER  # noqa: E402
from tp.providers.telegram import TelegramProvider, SingleFileProvider  # noqa: E402
from tp.providers.zoro import ZoroProvider  # noqa: E402


def test_registry():
    assert get('tg', 'auth') is fa.TgAuth
    assert get('tgp', 'auth') is fa.TgAuth
    assert get('agp', 'auth') is fa.AgpAuth
    assert get('axp', 'auth') is fa.AxpAuth
    assert get('zoro', 'auth') is fa.ZoroAuth
    assert REGISTRY['auth']


def test_wiring():
    assert type(TelegramProvider.auth) is fa.TgAuth
    assert type(SingleFileProvider.auth) is fa.TgAuth
    assert type(AnimeGateProvider.auth) is fa.AgpAuth
    assert type(AnimeXProvider.auth) is fa.AxpAuth
    assert type(ZoroProvider.auth) is fa.ZoroAuth


def test_default_referers_are_per_source():
    assert fa.AgpAuth().default_referer() == BASE + '/'
    assert fa.AxpAuth().default_referer() == MEDIA_REFERER
    assert fa.ZoroAuth().default_referer() is None   # stream carries its own
    assert fa.TgAuth().default_referer() is None     # telethon, no HTTP


def test_agp_dead_markers_and_source_scoping():
    for msg in ('no links (logged out / cookie expired?)',
                'no csrf token (page changed)',
                'no firefox cookies (log in...)',
                'HTTP Error 403: Forbidden'):
        assert fa.AgpAuth.dead('agp', 'https://animegate.ir/x', msg), msg
    assert fa.AgpAuth.dead('agp', 'https://animegate.ir/x',
                           'connection reset') is None
    assert fa.AgpAuth.dead('axp', 'axp:slug', 'HTTP Error 403') is None
    assert fa.TgAuth.dead('tg', '@chan 5', 'no firefox cookies') is None


def test_gui_scan_finds_only_the_matching_source():
    from tp import gui_all
    auth, dead = gui_all.MainWindow._auth_dead(
        'agp', 'https://animegate.ir/x', 'no firefox cookies (log in)')
    assert auth is fa.AgpAuth and 'firefox' in dead
    assert gui_all.MainWindow._auth_dead(
        'axp', 'axp:slug', 'connection reset') == (None, None)


def test_axp_headers_cache_is_per_host_and_cached():
    fa.AxpAuth._HDRS.clear()
    auth = fa.AxpAuth()

    class Http:
        def open(self, req):
            hdr = req.headers or {}
            r = mock.MagicMock()
            r.read.return_value = (b'#EXTM3U' if 'megaplay' in
                                   hdr.get('Referer', '') else b'xx')
            return r

        @staticmethod
        def request(url, headers=None, method='GET', data=None):
            r = mock.MagicMock()
            r.url, r.headers = url, headers
            return r

    out = auth.headers_for('https://cdn.host/a.m3u8', Http())
    assert out['Referer'] == MEDIA_REFERER           # first candidate wins
    assert fa.AxpAuth._HDRS['cdn.host'] == out
    out2 = auth.headers_for('https://cdn.host/b.m3u8', Http())
    assert out2 is out                               # cached per host
    fa.AxpAuth._HDRS.clear()


def test_agp_health_and_login_delegate_to_gateauth():
    auth = fa.AgpAuth()
    with mock.patch('tp.providers.animegate.GateAuth') as G:
        G.return_value.alive.return_value = (True, 'ok')
        assert auth.health() == (True, 'ok')
        auth.open_login()
        G.return_value.open_login.assert_called_once()


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('.', name)
    print('ok - test_features_auth')


if __name__ == '__main__':
    main()
