#!/usr/bin/env python3
"""test_features_audio - one Audio object per source, applied at play time.

axp and zoro own SEPARATE Audio classes: a regression in one can never pass
through the other's code. tg/agp own NoAudio (no-op, not capable).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.features import audio as fa  # noqa: E402
from tp.providers.animegate import AnimeGateProvider  # noqa: E402
from tp.providers.animex import AnimeXProvider  # noqa: E402
from tp.providers.telegram import TelegramProvider  # noqa: E402
from tp.providers.zoro import ZoroProvider  # noqa: E402


class _Fake:
    """Minimal provider double: records prepare() side effects."""
    def __init__(self):
        self.got = []
        self.audio_name = 'dub'

    def set_audio(self, value):
        self.got.append(value)


def test_registry_and_classes():
    # axp and zoro never share an Audio class
    assert type(AnimeXProvider.audio) is fa.AxpAudio
    assert type(ZoroProvider.audio) is fa.ZoroAudio
    assert isinstance(AnimeGateProvider.audio, fa.NoAudio)
    assert isinstance(TelegramProvider.audio, fa.NoAudio)
    from tp.features import REGISTRY, get
    assert get('axp', 'audio') is fa.AxpAudio
    assert get('zoro', 'audio') is fa.ZoroAudio
    assert REGISTRY['audio'].get('tg') is None


def test_axp_audio_prepare():
    p = _Fake()
    fa.AxpAudio().prepare(p, 'sub')
    assert p.got == ['sub']
    # blank choice falls back to dub (play-time contract)
    fa.AxpAudio().prepare(p, None)
    assert p.got == ['sub', None]   # axp's set_audio normalizes None->dub itself


def test_zoro_audio_prepare():
    p = _Fake()
    fa.ZoroAudio().prepare(p, 'auto')
    assert p.got == ['auto']
    # zoro keeps its current choice when play passes nothing
    fa.ZoroAudio().prepare(p, None)
    assert p.got == ['auto', None]


def test_no_audio_sources():
    na = fa.NoAudio()
    assert na.capable is False
    p = _Fake()
    assert na.prepare(p, 'sub') is None and p.got == []   # never touches axp/zoro code


def test_axp_real_provider_wiring():
    # the real AnimeX provider applies the audio choice (no network needed)
    prov = AnimeXProvider('axp:one-piece', audio='dub')
    assert prov.audio_name == 'dub'
    prov.audio.prepare(prov, 'sub')
    assert prov.audio_name == 'sub'


def test_axp_size_pref_via_quality_object():
    prov = AnimeXProvider('axp:one-piece', quality='nero 720p')
    prov.groups = [{'id': 'nero', 'label': 'nero  (dub)', 'qualities': []}]
    prov._providers = {'dub': ['nero'], 'sub': []}
    prov.select('nero 720p')
    assert prov._size_pref == '720p'
    prov.select('nero')
    assert prov._size_pref is None


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('.', name)
    print('ok - test_features_audio')


if __name__ == '__main__':
    main()
