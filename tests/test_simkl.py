#!/usr/bin/env python3
"""test_simkl - Simkl episode-title fallback (network mocked)."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.config import Config        # noqa: E402
from tp.metadata import Metadata    # noqa: E402
from tp.simkl import Simkl, _dig    # noqa: E402


def test_dig():
    assert _dig({'ids': {'simkl': 5}}, 'simkl') == 5
    assert _dig([{'ids': {'simkl': 7}}], 'simkl') == 7
    assert _dig(None, 'simkl') is None
    print('PASS simkl _dig')


def test_resolve_episodes():
    s = Simkl(client_id='x')
    calls = []

    def fake_get(path, **params):
        calls.append((path, params))
        if path == '/search/id':
            return {'ids': {'simkl': 42}}
        if path.startswith('/anime/episodes/'):
            return [{'episode': 1, 'title': 'The Beginning'},
                    {'episode': 2, 'title': 'The Journey'}]
        return None

    s._get = fake_get
    s._redirect = lambda **params: 42          # keyless resolution
    assert s.resolve(mal=60522) == 42
    assert s.resolve(mal=60522) == 42          # cached
    assert s.episode_title(2, mal=60522) == 'The Journey'
    assert s.episode_title(9, mal=60522) is None
    # resolution needs no client_id at all
    s2 = Simkl(client_id=None)
    s2._redirect = lambda **p: 99
    assert s2.resolve(mal=1) == 99
    print('PASS simkl resolve (keyless) + episodes')


def test_metadata_fallback():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-simkl-')).ensure()
    m = Metadata(cfg)
    m._jikan_title = lambda mal, ep: None  # MAL has no title for this donghua

    class FakeSimkl:
        def available(self):
            return True

        def episode_title(self, ep, mal=None, anilist=None, query=None):
            return f'Title {ep}'

    m.simkl = FakeSimkl()
    assert m.ep_title(59953, 3, title='Mu Shen Ji') == 'Title 3'

    class Boom:
        def available(self):
            return True

        def episode_title(self, *a, **k):
            raise AssertionError('should be served from cache')

    m.simkl = Boom()
    assert m.ep_title(59953, 3, title='Mu Shen Ji') == 'Title 3'
    print('PASS metadata simkl fallback + cache')


def main():
    test_dig()
    test_resolve_episodes()
    test_metadata_fallback()
    print('SIMKL OK')


if __name__ == '__main__':
    main()
