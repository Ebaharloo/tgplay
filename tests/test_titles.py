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


def test_metadata_title_merge():
    from tp.metadata import Metadata
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-mtitles-')).ensure()
    m = Metadata(cfg)
    calls = {'n': 0}
    state = {'list': {1: 'A', 2: 'B'}}

    def fake(mal_id):
        calls['n'] += 1
        return dict(state['list'])

    m._mal_titles = fake
    assert m._mal_title(999, 1) == 'A' and calls['n'] == 1
    assert m._mal_title(999, 2) == 'B' and calls['n'] == 1   # known: no refetch
    state['list'][3] = 'C'                                   # a new episode aired
    m2 = Metadata(cfg)                                       # next run
    m2._mal_titles = fake
    assert m2._mal_title(999, 3) == 'C' and calls['n'] == 2   # synced the new ep
    state['list'][1] = 'CHANGED'                             # source rewritten
    m3 = Metadata(cfg)
    m3._mal_titles = fake
    assert m3._mal_title(999, 4) is None                     # triggers a refresh
    assert m3._mal_title(999, 1) == 'A'                      # never overwritten
    print('PASS metadata title merge (fetch once, never overwrite, sync new)')


def test_retry_missing_each_run():
    from tp.metadata import Metadata
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-retry-')).ensure()
    src = {'list': {1: 'A'}}

    def fake(mal_id):
        return dict(src['list'])

    m = Metadata(cfg)
    m._mal_titles = fake
    assert m._mal_title(7, 1) == 'A'
    assert m._mal_title(7, 2) is None          # name not available yet
    src['list'][2] = 'B'                        # it appears later (or site back)
    m2 = Metadata(cfg)                          # next run
    m2._mal_titles = fake
    assert m2._mal_title(7, 2) == 'B'           # retried and found
    assert m2._mal_title(7, 1) == 'A'           # known one untouched
    print('PASS titles retry missing each run')


def main():
    test_instant_then_bg()
    test_breaker()
    test_upto()
    test_metadata_title_merge()
    test_retry_missing_each_run()
    print('TITLES OK')


if __name__ == '__main__':
    main()
