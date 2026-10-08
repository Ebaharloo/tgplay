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


def test_metadata_title_merge():
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
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-retry-')).ensure()
    src = {'list': {1: 'A'}}

    def fake(mal_id):
        return dict(src['list'])

    m = Metadata(cfg)
    m._mal_titles = fake
    assert m._mal_title(7, 1) == 'A'
    assert m._mal_title(7, 2) is None          # name not available yet
    src['list'][2] = 'B'                        # appears later (or site is back)
    m2 = Metadata(cfg)                          # next run
    m2._mal_titles = fake
    assert m2._mal_title(7, 2) == 'B'           # retried and found
    assert m2._mal_title(7, 1) == 'A'           # known one untouched
    print('PASS titles retry missing each run')


def main():
    test_labels_instant()
    test_metadata_title_merge()
    test_retry_missing_each_run()
    print('TITLES OK')


if __name__ == '__main__':
    main()
