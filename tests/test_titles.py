#!/usr/bin/env python3
"""test_titles - instant cache reads + Metadata one-time / merge / retry."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.config import Config      # noqa: E402
from tp.metadata import Metadata  # noqa: E402
from tp.titles import TitleService  # noqa: E402


def test_labels_instant():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-labels-')).ensure()
    json.dump({'51289': {'1': 'One', '2': 'Two'}}, open(cfg.ep_titles, 'w'))
    ts = TitleService(Metadata(cfg), cfg)
    eps = {1: 'قسمت: 1', 2: 'قسمت: 2', 3: 'قسمت: 3'}
    got = ts.labels(51289, eps)
    assert got[1] == 'One' and got[2] == 'Two' and got[3] == 'قسمت: 3', got
    assert ts.get(51289, 2) == 'Two' and ts.get(51289, 9) is None
    print('PASS labels instant from cache')


def test_simkl_titles_merged():
    """The THIRD named source (after MAL and Bangumi-Chinese): Simkl episode
    names merge under 'simkl:{mal}' - exactly the key TitleService reads."""
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-simkl-t-')).ensure()
    m = Metadata(cfg)

    class FakeSimkl:
        def __init__(self):
            self._eps = {1: 'Real Name One', 2: 'Episode 2', 3: 'Real Name 3'}

        def available(self):
            return True

        def resolve(self, mal=None, anilist=None, query=None):
            return 424242

        def episodes(self, simkl_id):
            assert simkl_id == 424242
            return dict(self._eps)

    m.simkl = FakeSimkl()
    got = m.simkl_titles(46000)
    assert got[1] == 'Real Name One', got
    cache = json.load(open(cfg.ep_titles))
    merged = cache['simkl:46000']
    assert merged == {'1': 'Real Name One', '3': 'Real Name 3'}, merged \
        # generic 'Episode 2' is never stored
    ts = TitleService(m, cfg)
    labels = ts.labels(46000, {1: 'Episode 1', 2: 'Episode 2', 3: 'Episode 3'})
    assert labels[1] == 'Real Name One' and labels[3] == 'Real Name 3', labels
    assert labels[2] == 'Episode 2', labels        # generic stays placeholder
    # names already cached are never overwritten (the merge-once rule)
    SanityCheck = m.simkl_titles(46000)
    assert SanityCheck[1] == 'Real Name One'
    print('PASS Simkl episode names merged + read by labels')


def test_metadata_title_merge():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-mtitles-')).ensure()
    m = Metadata(cfg)
    calls = {'n': 0}
    state = {'list': {1: 'A', 2: 'B'}}

    def fake(mal_id):
        calls['n'] += 1
        return dict(state['list'])

    m._mal_titles = fake
    m._cjk_title = lambda *a: None
    assert m._mal_title(999, 1) == 'A' and calls['n'] == 1
    assert m._mal_title(999, 2) == 'B' and calls['n'] == 1   # known: no refetch
    state['list'][3] = 'C'                                   # a new episode aired
    m2 = Metadata(cfg)                                       # next run
    m2._mal_titles = fake
    m2._cjk_title = lambda *a: None
    assert m2._mal_title(999, 3) == 'C' and calls['n'] == 2   # synced the new ep
    state['list'][1] = 'CHANGED'                             # source rewritten
    m3 = Metadata(cfg)
    m3._mal_titles = fake
    m3._cjk_title = lambda *a: None
    assert m3._mal_title(999, 4) is None                     # triggers a refresh
    assert m3._mal_title(999, 1) == 'A'                      # never overwritten
    print('PASS metadata title merge (fetch once, never overwrite, sync new)')


def test_retry_missing_each_run():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-retry-')).ensure()
    src = {'list': {1: 'A'}}

    def fake(mal_id):
        return dict(src['list'])

    m = Metadata(cfg)
    m._mal_titles = fake
    m._cjk_title = lambda *a: None
    assert m._mal_title(7, 1) == 'A'
    assert m._mal_title(7, 2) is None          # name not available yet
    src['list'][2] = 'B'                        # appears later (or site is back)
    m2 = Metadata(cfg)                          # next run
    m2._mal_titles = fake
    m2._cjk_title = lambda *a: None
    assert m2._mal_title(7, 2) == 'B'           # retried and found
    assert m2._mal_title(7, 1) == 'A'           # known one untouched
    print('PASS titles retry missing each run')


def test_labels_translated():
    from tp.titles import TitleService
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-trlab-')).ensure()
    json.dump({'59953': {'1': '天黑别出门'}}, open(cfg.ep_titles, 'w'))
    json.dump({'天黑别出门': "Don't go outside when it's dark"},
              open(cfg.translations, 'w'))
    ts = TitleService(Metadata(cfg), cfg)
    assert ts.labels(59953, {1: 'x'})[1] == "Don't go outside when it's dark"
    print('PASS labels translated to English')


def main():
    test_labels_instant()
    test_simkl_titles_merged()
    test_labels_translated()
    test_metadata_title_merge()
    test_retry_missing_each_run()
    print('TITLES OK')


if __name__ == '__main__':
    main()
