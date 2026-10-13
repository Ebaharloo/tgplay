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
    # painting guard: names apply only when the cached list lines up with
    # this page's episode count (an id pins WHICH entry, not the numbering)
    json.dump({'51289': {'1': 'One', '2': 'Two', '3': 'Three'}},
              open(cfg.ep_titles, 'w'))
    ts = TitleService(Metadata(cfg), cfg)
    eps = {1: 'قسمت: 1', 2: 'قسمت: 2', 3: 'قسمت: 3'}
    got = ts.labels(51289, eps)
    assert got[1] == 'One' and got[2] == 'Two' and got[3] == 'Three', got
    # mismatched count (a merged 2-ep page) paints NOTHING - placeholders keep
    # the show honest instead of showing another season's names
    got2 = ts.labels(51289, {1: 'Episode 1', 2: 'Episode 2'})
    assert got2[1] == 'Episode 1' and got2[2] == 'Episode 2', got2
    assert ts.get(51289, 2) == 'Two' and ts.get(51289, 9) is None
    # chinese-numbering rows (第一百六十六集) are generic - never painted
    json.dump({'777': {'1': '第一百六十六集', '2': '第一百六十七集'}},
              open(cfg.ep_titles, 'w'))
    got3 = ts.labels(777, {1: 'Episode 1', 2: 'Episode 2'})
    assert got3 == {1: 'Episode 1', 2: 'Episode 2'}, got3
    print('PASS labels instant (guarded painting) + generic CJK skipped')


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
    # paint guard: names may only be painted when the cached numbers line
    # up with the page; the merged list covers {1,3} so a matching 2-ep
    # page gets them...
    labels = ts.labels(46000, {1: 'Episode 1', 3: 'Episode 3'})
    assert labels[1] == 'Real Name One' and labels[3] == 'Real Name 3', labels
    # ...while a 3-ep page (different numbering) paints NOTHING - no mixing
    labels2 = ts.labels(46000, {1: 'Episode 1', 2: 'Episode 2',
                                3: 'Episode 3'})
    assert labels2 == {1: 'Episode 1', 2: 'Episode 2', 3: 'Episode 3'}, labels2
    # names already cached are never overwritten (the merge-once rule)
    SanityCheck = m.simkl_titles(46000)
    assert SanityCheck[1] == 'Real Name One'
    print('PASS Simkl episode names merged + paint-guard honored')


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


def test_release_date_prefix_cleaned():
    """Bangumi names unaired episodes 'Release: 2026/09/03 15:00 GMT - name';
    the episode list must show the NAME, never a date prefix."""
    from tp.titles import clean_ep_name
    assert clean_ep_name('Release: 2026/09/03 15:00 GMT - My Little Sis Is '
                         'Popular, Nya') == 'My Little Sis Is Popular, Nya'
    assert clean_ep_name('Release: 2026/09/03 - Kyoto Trip') == 'Kyoto Trip'
    assert clean_ep_name('Release: 2026-09-03 15:00 UTC - X') == 'X'
    assert clean_ep_name('Release: 2026/09/03 15:00 GMT') == ''  # date only
    assert clean_ep_name('Normal Name') == 'Normal Name'

    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-rel-')).ensure()
    json.dump({'777': {'9': 'Release: 2026/09/03 15:00 GMT - Little Sis',
                       '10': 'Already Fine'},
               'simkl:777': {'11': 'Release: 2026/09/24 15:00 GMT - Final'}},
              open(cfg.ep_titles, 'w'))
    ts = TitleService(Metadata(cfg), cfg)
    labels = ts.labels(777, {9: 'Episode 9', 10: 'Episode 10',
                             11: 'Episode 11'})
    assert labels[9] == 'Little Sis', labels          # legacy cache: cleaned
    assert labels[10] == 'Already Fine', labels
    assert labels[11] == 'Final', labels              # simkl key too
    print('PASS release-date prefix stripped from episode names')


def main():
    test_labels_instant()
    test_simkl_titles_merged()
    test_release_date_prefix_cleaned()
    test_labels_translated()
    test_metadata_title_merge()
    test_retry_missing_each_run()
    print('TITLES OK')


if __name__ == '__main__':
    main()
