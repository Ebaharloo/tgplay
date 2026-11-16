#!/usr/bin/env python3
"""test_continuewatch - own test model for the "Continue watching" shelf (tp.continuewatch).

The shelf is pure data: which Simkl rows are in progress, in what order, which
poster each row gets.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import continuewatch  # noqa: E402


class FakeArt:
    def __init__(self, covers=None):
        self.covers_map = covers or {}
        self.asked = []

    def covers(self, mal_ids):
        self.asked.append(list(mal_ids))
        return {m: self.covers_map[m] for m in mal_ids if m in self.covers_map}


def shelf(art=None):
    return continuewatch.ContinueWatching(cfg=None, art=art or FakeArt())


def test_only_started_unfinished_shows():
    rem = [
        {'title': 'Started', 'watched': 3, 'next_ep': 4, 'total': 12},
        {'title': 'Untouched', 'watched': 0, 'next_ep': 1, 'total': 12},
        {'title': 'Finished', 'watched': 12, 'next_ep': 13, 'total': 12},
        {'title': '', 'watched': 2, 'next_ep': 3, 'total': 12},
        {'title': 'Bad numbers', 'watched': 'x', 'next_ep': 3, 'total': 12},
    ]
    assert [r['title'] for r in shelf().items(rem)] == ['Started']


def test_newest_activity_first_and_deduped():
    rem = [
        {'title': 'Old', 'watched': 2, 'next_ep': 3, 'total': 10, 'last_watched': '2026-01-01'},
        {'title': 'New', 'watched': 5, 'next_ep': 6, 'total': 10, 'last_watched': '2026-11-01'},
        {'title': 'NEW', 'watched': 5, 'next_ep': 6, 'total': 10, 'last_watched': '2026-10-01'},
    ]
    got = shelf().items(rem, limit=10)
    assert [r['title'] for r in got] == ['New', 'Old']
    assert got[0]['pct'] == 50.0


def test_limit_and_poster_choice():
    art = FakeArt({7: 'https://anilist/cover.jpg'})
    rem = [
        {'title': 'SimklPoster', 'watched': 1, 'next_ep': 2, 'total': 12,
         'poster': 'abc/def', 'last_watched': '2026-11-02'},
        {'title': 'AniListCover', 'watched': 1, 'next_ep': 2, 'total': 12,
         'mal': 7, 'last_watched': '2026-11-01'},
    ]
    got = shelf(art).items(rem, limit=1)
    assert len(got) == 1
    assert got[0]['image'] == continuewatch.SIMKL_POSTER.format(path='abc/def')
    got = shelf(art).items(rem, limit=10)
    assert got[1]['image'] == 'https://anilist/cover.jpg'
    assert art.asked == [[7]]


if __name__ == '__main__':
    raise SystemExit(__import__('pytest').main([__file__, '-q']))
