#!/usr/bin/env python3
"""test_features_titles - episode-name knowledge per source.

agp/axp/zoro paint real names from the pinned MAL entry (axp additionally
strips Bangumi's release-date marker and trusts the API's malId; zoro does
no season guard and no background fetch); tg/tgp use the .mkv file name and
never touch MAL.
"""
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.features import REGISTRY, get  # noqa: E402
from tp.features import titles as ft  # noqa: E402
from tp.providers.animegate import AnimeGateProvider  # noqa: E402
from tp.providers.animex import AnimeXProvider  # noqa: E402
from tp.providers.telegram import TelegramProvider, SingleFileProvider  # noqa: E402
from tp.providers.zoro import ZoroProvider  # noqa: E402


def test_registry():
    assert get('tg', 'titles') is ft.TgTitles
    assert get('tgp', 'titles') is ft.TgTitles
    assert get('agp', 'titles') is ft.MalTitles
    assert get('axp', 'titles') is ft.AxpTitles
    assert get('zoro', 'titles') is ft.ZoroTitles
    assert REGISTRY['titles']


def test_wiring():
    assert type(TelegramProvider.titles) is ft.TgTitles
    assert type(SingleFileProvider.titles) is ft.TgTitles
    assert type(AnimeGateProvider.titles) is ft.MalTitles
    assert type(AnimeXProvider.titles) is ft.AxpTitles
    assert type(ZoroProvider.titles) is ft.ZoroTitles


class Meta:
    _refreshed = set()

    def link_mal(self, target):
        return 123

    def remember_link_mal(self, target, mal):
        self.pinned = (target, mal)


class Svc:
    """TitleService double: paint 'Episode N' from its cache."""

    def labels(self, mal, base):
        return {n: (f'Painted {n}' if str(t).startswith('Episode ')
                    else t) for n, t in base.items()}

    def cache_count(self, mal):
        return 0


def test_tg_uses_file_names_never_mal():
    class Prov:
        title = 'chan/5'
        def episodes(self):
            return {1: 'show - ep1.mkv', 2: 'show - ep2.mkv'}

    with mock.patch.object(ft, 'safe_mal') as sm:
        labels, mal = ft.TgTitles().open_labels(Prov(), Meta(), Svc(), 'x')
    assert mal is None and labels == {1: 'show - ep1.mkv', 2: 'show - ep2.mkv'}
    assert not sm.called            # tg never resolves MAL


def test_agp_pins_mal_and_paints():
    class Prov:
        title = 'Some Anime'
        def episodes(self):
            return {1: 'Episode 1', 2: 'Named ep'}

    meta, svc = Meta(), Svc()
    th_run = []
    with mock.patch.object(ft.threading, 'Thread') as Th, \
            mock.patch.object(ft, 'safe_mal') as sm:
        Th.return_value.start.side_effect = lambda: th_run.append(1)
        Th.return_value.is_alive.return_value = False
        labels, mal = ft.MalTitles().open_labels(Prov(), meta, svc, 'agp:link')
    assert mal == 123
    assert meta.pinned == ('agp:link', 123)
    assert labels == {1: 'Painted 1', 2: 'Named ep'}


def test_axp_strips_release_marker_and_trusts_api_malid():
    class Prov:
        title = 'Some Anime'
        mal_id = 777
        def episodes(self):
            return {1: 'Release: 2026/09/03 15:00 GMT - Little Sis',
                    2: 'Fine Name', 3: 'Episode 3'}

    meta = Meta()
    with mock.patch.object(ft, 'safe_mal') as sm:
        labels, mal = ft.AxpTitles().open_labels(Prov(), meta, Svc(), 'axp:link')
    assert mal == 777               # provider's exact id wins over the link pin
    assert labels[1] == 'Little Sis'  # marker stripped, real name kept
    assert labels[2] == 'Fine Name'
    assert labels[3] == 'Painted 3'   # stub name painted from MAL
    assert not sm.called


def test_axp_marker_stripping_is_only_axp():
    """agp/zoro show raw provider titles; axp is the only cleaner."""
    base = {1: 'Release: 2026/09/03 15:00 GMT - Little Sis'}
    class AgpProv:
        title = 'x'
        def episodes(self):
            return dict(base)
    out = ft.MalTitles().provider_labels(AgpProv())
    assert out[1].startswith('Release:')


def test_zoro_paints_but_no_guard_no_fetch():
    class Prov:
        title = 'Some Anime'
        def episodes(self):
            return {1: 'Episode 1', 2: 'Episode 2'}

    meta, svc = Meta(), Svc()
    th_run = []
    with mock.patch.object(ft.threading, 'Thread') as Th:
        Th.return_value.start.side_effect = lambda: th_run.append(1)
        labels, mal = ft.ZoroTitles().open_labels(Prov(), meta, svc, 'zoro:link')
    assert mal == 123 and labels == {1: 'Painted 1', 2: 'Painted 2'}
    assert not Th.called            # zoro: no background fetch thread
    with mock.patch('tp.log.cprint') as cp:
        ft.ZoroTitles().season_guard(meta, svc, 123, {1: 'Episode 1'})
        assert not cp.called        # zoro: no season-mismatch guard


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('.', name)
    print('ok - test_features_titles')


if __name__ == '__main__':
    main()
