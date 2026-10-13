#!/usr/bin/env python3
"""test_finder - the id-first show finder (tp.finder.ShowFinder), mocked.

No network: provider search + the Simkl record are stubbed. Checks that
- a candidate whose malId equals a known id is ranked FIRST and flagged
  matched='id',
- AnimeGate (no ids) is searched under EVERY known name form (English +
  romanized + CJK from the Simkl alt titles) and scored against them all,
- candidates carry their ids so the UI can pin the MAL id onto the link,
- pin() writes the id so open_session reads it back.
Run: .venv/bin/python tests/test_finder.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import finder  # noqa: E402
from tp.config import Config  # noqa: E402

RECORD = {'title': 'A Record Of Mortal\'s Journey To Immortality',
          'ids': {'simkl': 1402127, 'mal': 41219, 'anilist': 11},
          'alt_titles': [{'name': 'Fanren Xiu Xian Zhuan'},
                         {'name': '凡人修仙传：风起天南'}]}

AGP_HITS = {'fanren xiu xian zhuan':
            [{'title': 'Fanren Xiu Xian Chuan',
              'url': 'https://animegate.ir/anime/fanren-xiu-xian-chuan-18582',
              'source': 'agp'}],
            'a record of mortal\'s journey to immortality': [
                {'title': 'Some Other Show', 'url': 'https://animegate.ir/anime/x-1',
                 'source': 'agp'}]}

AXP_HITS = [
    {'title': 'Unrelated Show', 'url': 'axp:noise-1', 'source': 'axp',
     'malId': 999999, 'anilistId': 1},
    {'title': "A Record Of Mortal's Journey To Immortality",
     'url': 'axp:a-record-of-mortals-journey-to-immortality-psj88',
     'source': 'axp', 'malId': 41219, 'anilistId': 500},
]


class FakeSimkl:
    def available(self):
        return True

    def info(self, mal=None, anilist=None, query=None):
        return RECORD


def _stub(f, hits_agp, hits_axp):
    """Point ShowFinder's provider lookups at canned hits + a fake Simkl."""
    def one(src, name):
        if src == 'axp':
            return list(hits_axp)
        return list(hits_agp.get(name.casefold()) or [])
    f._search_one = one
    f._record = lambda k: dict(RECORD)


def test_axp_id_match_ranks_first():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-fnd-')).ensure()
    f = finder.ShowFinder(cfg, http=None)
    _stub(f, AGP_HITS, AXP_HITS)
    out = f.find(title="A Record Of Mortal's Journey To Immortality")
    assert out, 'expected candidates'
    assert out[0]['matched'] == 'id', out[0]
    assert out[0]['url'] == 'axp:a-record-of-mortals-journey-to-immortality-psj88', out[0]
    assert out[0]['ids'].get('mal') == 41219, out[0]
    print('PASS id-first: the AnimeX hit with the known malId wins')


def test_agp_found_by_site_name():
    """The site names the show 'Fanren Xiu Xian Chuan' (romanized, spelled
    differently) - the alt-title query still finds it and ranks it by the
    name similarity, not by luck."""
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-fnd-')).ensure()
    f = finder.ShowFinder(cfg, http=None)
    _stub(f, AGP_HITS, AXP_HITS)
    out = f.find(title="A Record Of Mortal's Journey To Immortality")
    agp = [c for c in out if c['source'] == 'agp']
    assert agp, [c['url'] for c in out]
    best = agp[0]
    assert best['url'].endswith('fanren-xiu-xian-chuan-18582'), best
    assert best['score'] >= 0.5, best          # similar to a known name
    print('PASS alt-title query finds the romanized AnimeGate page')


def test_pin_id_to_link():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-fnd-')).ensure()
    f = finder.ShowFinder(cfg, http=None)
    _stub(f, AGP_HITS, AXP_HITS)
    out = f.find(title="A Record Of Mortal's Journey To Immortality")
    url = out[0]['url']
    assert f.meta.link_mal(url) is None
    f.pin(out[0])
    assert f.meta.link_mal(url) == 41219, f.meta.link_mal(url)
    print('PASS pin: the picked candidate\'s MAL id sticks to its link')


def test_no_ids_still_finds_by_names():
    """A plain typed search (no ids anywhere) must still work."""
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-fnd-')).ensure()
    f = finder.ShowFinder(cfg, http=None)
    _stub(f, AGP_HITS, AXP_HITS)
    out = f.find(title='Fanren Xiu Xian Zhuan')
    assert out and out[0]['score'] > 0.5, out[:2]
    print('PASS name-only search (no ids) still returns hits')


def test_entry_ids_are_trusted_and_pinned():
    """A sidebar row's simkl id resolves the record DIRECTLY (its own
    season), and those ids are trusted - so AGP candidates (which carry no
    ids of their own) get pinned to the right MAL entry."""
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-fnd-')).ensure()
    f = finder.ShowFinder(cfg, http=None)
    _stub(f, AGP_HITS, [])
    out = f.find(entry={'title': "A Record Of Mortal's Journey To Immortality",
                        'simkl': 1402127})
    agp = [c for c in out if c['source'] == 'agp']
    assert agp and agp[0]['ids'].get('mal') == 41219, agp
    f.pin(agp[0])
    assert f.meta.link_mal(agp[0]['url']) == 41219
    print('PASS sidebar-entry ids are trusted and pinned onto AGP links')


def test_fuzzy_record_must_match_the_title():
    """If Simkl's first search hit is some OTHER show, its ids must NOT be
    attached to the candidates (a wrong pin is worse than no pin)."""
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-fnd-')).ensure()
    f = finder.ShowFinder(cfg, http=None)
    bogus = {'title': 'Unrelated Anime', 'ids': {'mal': 111},
             'alt_titles': []}

    def one(src, name):
        return list(AXP_HITS) if src == 'axp' else []
    f._search_one = one
    f._record = lambda k: dict(bogus)
    out = f.find(title='Totally Different Show Name')
    assert out, 'candidates still returned'
    for c in out:                       # only the candidate's OWN id may stick
        assert c['ids'].get('mal') in (None, c.get('malId')), c
    print('PASS fuzzy mismatch does not attach wrong ids')


def main():
    test_axp_id_match_ranks_first()
    test_agp_found_by_site_name()
    test_pin_id_to_link()
    test_no_ids_still_finds_by_names()
    test_entry_ids_are_trusted_and_pinned()
    test_fuzzy_record_must_match_the_title()
    print('FINDER OK')


if __name__ == '__main__':
    main()
