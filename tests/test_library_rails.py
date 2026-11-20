#!/usr/bin/env python3
"""test_library_rails - history/continue union of Simkl + AniList rows."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.library import _merge_remote_rows                   # noqa: E402


def _simkl(title, watched, last):
    return {'title': title, 'simkl': 1, 'mal': 2, 'anilist': None,
            'status': 'watching', 'watched': watched, 'total': 12,
            'next_ep': watched + 1, 'air_date': None, 'last_watched': last}


def _anilist(title, watched, last, aid=77):
    return {'title': title, 'simkl': None, 'mal': 2, 'anilist': aid,
            'status': 'watching', 'watched': watched, 'total': 12,
            'next_ep': watched + 1, 'air_date': None, 'last_watched': last}


def test_anilist_only_show_appends():
    rows = _merge_remote_rows([_simkl('Show A', 3, '2026-11-19 10:00')],
                              [_anilist('Show B', 5, '2026-11-20 09:00')])
    titles = sorted(r['title'] for r in rows)
    assert titles == ['Show A', 'Show B'], titles
    b = next(r for r in rows if r['title'] == 'Show B')
    assert b['anilist'] == 77 and b['next_ep'] == 6


def test_union_takes_higher_progress_and_newer_last_watched():
    rows = _merge_remote_rows(
        [_simkl('Show A', 3, '2026-11-19 10:00')],
        [_anilist('Show A', 8, '2026-11-20 09:00', aid=77)])
    r = rows[0]
    assert len(rows) == 1
    assert r['simkl'] == 1 and r['anilist'] == 77      # ids joined
    assert r['watched'] == 8 and r['next_ep'] == 9     # higher progress wins
    assert r['last_watched'] == '2026-11-20 09:00'     # newer date wins


def test_case_and_spacing_match_titles():
    rows = _merge_remote_rows(
        [_simkl('One  Piece', 3, '2026-11-19')],
        [_anilist('one piece', 2, '2026-11-18')])
    assert len(rows) == 1 and rows[0]['watched'] == 3


if __name__ == '__main__':
    for n, f in sorted(globals().items()):
        if n.startswith('test_'):
            f()
            print('ok', n)
