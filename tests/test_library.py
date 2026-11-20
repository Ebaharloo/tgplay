#!/usr/bin/env python3
"""test_library - own test model for Simkl-library search matching (tp.library).

Pure helpers only: the network paths (overview/search_variants) are covered by
the caller suites; this pins the title matching the GUI list depends on.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import library  # noqa: E402


def test_title_variants_keep_full_name_first_and_drop_the_year():
    got = library.title_variants("A Record of Mortal's Journey to Immortality (2024)")
    assert got[0] == "A Record of Mortal's Journey to Immortality (2024)"
    assert "A Record of Mortal's Journey to Immortality" in got
    assert library.title_variants('') == []


def test_title_variants_strip_a_season_suffix():
    assert 'Bleach' in library.title_variants('Bleach Season 2')


def test_norm_title_collapses_wrapping():
    assert library._norm_title('A  Show\n  Title ') == 'a show title'


def test_ranked_closest_title_first_and_axp_wins_ties():
    rows = [
        {'title': 'Something Else', 'source': 'agp', 'url': 'a'},
        {'title': 'Bleach', 'source': 'agp', 'url': 'b'},
        {'title': 'Bleach', 'source': 'axp', 'url': 'c', 'malId': 269},
    ]
    got = library.ranked(rows, 'bleach')
    assert got[0]['url'] == 'c', [r['url'] for r in got]   # same title -> axp (dub) first
    assert got[2]['url'] == 'a'
    assert library._norm_has_exact(rows, 'BLEACH') is True


def main():
    test_title_variants_keep_full_name_first_and_drop_the_year()
    test_title_variants_strip_a_season_suffix()
    test_norm_title_collapses_wrapping()
    test_ranked_closest_title_first_and_axp_wins_ties()
    print('LIBRARY OK')


if __name__ == '__main__':
    main()
