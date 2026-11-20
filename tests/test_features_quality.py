#!/usr/bin/env python3
"""test_features_quality - the server/size menu per source.

AxpQuality splits its 'server · size' labels (the GUI used to parse them by
itself); agp/tg list plain labels; zoro offers no rendition menu. axp and zoro
never share Quality code.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.features import get  # noqa: E402
from tp.features import quality as fq  # noqa: E402
from tp.providers.animegate import AnimeGateProvider  # noqa: E402
from tp.providers.animex import AnimeXProvider  # noqa: E402
from tp.providers.telegram import TelegramProvider  # noqa: E402
from tp.providers.zoro import ZoroProvider  # noqa: E402


def test_registry():
    assert get('axp', 'quality') is fq.AxpQuality
    assert get('agp', 'quality') is fq.AgpQuality
    assert get('tg', 'quality') is fq.TgQuality
    assert get('zoro', 'quality') is None       # zoro has none (NoQuality)


def test_axp_menus_split_server_and_size():
    q = fq.AxpQuality()
    groups = [{'label': 'nero  (dub+sub)  ·  1080p', 'qualities': ['1080p', '720p']},
              {'label': 'yuki  (sub)', 'qualities': []}]
    sources, size_map = q.menus(groups)
    assert sources == ['nero', 'yuki']
    assert size_map['nero'] == ['1080p', '720p'] and size_map['yuki'] == []
    # legacy label form (no qualities key) still parses the '· 1080p' tail
    sources, size_map = q.menus([{'label': 'nero  (dub)  ·  720p'}])
    assert size_map == {'nero': ['720p']}
    # non-size tails are not sizes
    _, size_map = q.menus([{'label': 'nero  (dub)  ·  not serving'}])
    assert size_map == {'nero': []}


def test_axp_size_pref():
    q = fq.AxpQuality()
    assert q.size_pref('nero 720p') == '720p'
    assert q.size_pref('NERO 1080P') == '1080p'
    assert q.size_pref('nero') == ''
    assert q.size_pref(None) == ''


def test_plain_sources_list_labels():
    groups = [{'label': '720p'}, {'label': '1080p'}]
    for cls in (fq.TgQuality, fq.AgpQuality, fq.NoQuality):
        sources, size_map = cls().menus(groups)
        assert sources == ['720p', '1080p'] and size_map == {}, cls


def test_tg_quality_filename_grouping():
    names = ['e 480p.mkv', 'e 1080p.mkv', 'e no-tag.mkv']
    qs, byq = TelegramProvider.quality.group(names)
    assert qs == ['480p', '1080p']
    assert all('e no-tag.mkv' in v for v in byq.values())


def test_real_provider_wiring():
    assert type(AnimeXProvider.quality) is fq.AxpQuality
    assert type(AnimeGateProvider.quality) is fq.AgpQuality
    assert type(TelegramProvider.quality) is fq.TgQuality
    assert type(ZoroProvider.quality) is fq.NoQuality


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('.', name)
    print('ok - test_features_quality')


if __name__ == '__main__':
    main()
