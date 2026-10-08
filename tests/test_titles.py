#!/usr/bin/env python3
"""test_titles - non-blocking title cache: instant reads, background fill,
circuit-breaker-aware, bounded by `upto`."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.config import Config      # noqa: E402
from tp.titles import TitleService  # noqa: E402


class FakeMeta:
    def __init__(self, cfg, down=()):
        self.cfg = cfg
        self._down = set(down)
        self.calls = []

    def cached_mal(self, title):
        return 51289

    def resolve_mal(self, title, ask=False):
        return 51289

    def down(self, src):
        return src in self._down

    def ep_title(self, mal, ep, title=None, anilist_id=None):
        self.calls.append(ep)
        d = (json.load(open(self.cfg.ep_titles))
             if os.path.exists(self.cfg.ep_titles) else {})
        d.setdefault(str(mal), {})[str(ep)] = f'T{ep}'
        json.dump(d, open(self.cfg.ep_titles, 'w'))
        return f'T{ep}'


def test_instant_then_bg():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-titles-')).ensure()
    m = FakeMeta(cfg)
    ts = TitleService(m, cfg)
    eps = {1: 'a', 2: 'b', 3: 'c'}
    assert ts.labels(51289, eps) == eps          # instant: nothing cached yet
    ts.start('X', [1, 2, 3]).join(5)
    got = ts.labels(51289, eps)
    assert got[1] == 'T1' and got[3] == 'T3', got
    assert m.calls == [1, 2, 3], m.calls
    print('PASS titles instant + background fill')


def test_breaker():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-titles-')).ensure()
    m = FakeMeta(cfg, down=('jikan', 'simkl'))
    ts = TitleService(m, cfg)
    ts.start('X', [1, 2, 3]).join(2)
    assert m.calls == [], m.calls                # every source cooling down
    print('PASS titles breaker stops fetching')


def test_upto():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-titles-')).ensure()
    m = FakeMeta(cfg)
    ts = TitleService(m, cfg)
    ts.start('X', [1, 2, 3, 4, 5], upto=3).join(5)
    assert m.calls == [1, 2, 3], m.calls
    print('PASS titles upto limit')


def main():
    test_instant_then_bg()
    test_breaker()
    test_upto()
    print('TITLES OK')


if __name__ == '__main__':
    main()
