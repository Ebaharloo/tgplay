#!/usr/bin/env python3
"""test_fandom - Fandom wiki character rosters (mocked API).

Covers: subdomain candidate order, Category:Characters parsing, junk titles
filtered, thumbnails mapped, link URLs - all without network.
Run: .venv/bin/python tests/test_fandom.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.fandom import FandomCharacters, wiki_candidates  # noqa: E402


def test_candidates():
    c = wiki_candidates(['Renegade Immortal', 'Xian Ni', '仙逆'])
    assert c[0] == 'renegade-immortal', c
    assert 'xian-ni' in c, c
    assert 'renegadeimmortal' in c, c
    assert len(c) == len(set(c)), c
    print('PASS wiki candidates from the show name (deduped, ordered)')


def test_fetch_rows():
    f = FandomCharacters()
    seen = []

    def fake_api(sub, params):
        seen.append((sub, params.get('list') or params.get('prop')))
        if sub.startswith('renegade'):        # those wikis don't exist
            return None                       # -> falls through to xian-ni
        if params.get('list') == 'categorymembers':
            return {'query': {'categorymembers': [
                {'title': 'Wang Lin'}, {'title': 'Li Muwan'},
                {'title': 'Situ Nan'}, {'title': 'Characters'}]}}
        if params.get('prop') == 'pageimages':
            return {'query': {'pages': {
                str(i): {'title': t,
                         'thumbnail': {'source': f'https://img/{t}'}}
                for i, t in enumerate(params['titles'].split('|'))}}}
        return None

    f._api = fake_api
    rows = f.fetch(['Renegade Immortal', 'Xian Ni'])
    assert len(rows) == 3, rows               # the 'Characters' page skipped
    assert {r['name'] for r in rows} == {'Wang Lin', 'Li Muwan', 'Situ Nan'}
    assert rows[0]['from'] == 'wiki' and rows[0]['wiki'] == 'xian-ni'
    assert rows[0]['url'] == 'https://xian-ni.fandom.com/wiki/Wang_Lin'
    assert rows[0]['image'] == 'https://img/Wang Lin'
    assert ('xian-ni', 'categorymembers') in seen
    print('PASS wiki roster rows (names, links, thumbnails, junk filtered)')


def main():
    test_candidates()
    test_fetch_rows()
    print('FANDOM OK')


if __name__ == '__main__':
    main()
