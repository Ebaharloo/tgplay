#!/usr/bin/env python3
"""test_tracking - AniList progress logic (network mocked)."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.config import Config       # noqa: E402
from tp.tracking import Tracker    # noqa: E402


def test():
    cfg = Config(home=tempfile.mkdtemp(prefix='tgplay-trk-')).ensure()
    tr = Tracker(cfg)

    # progress.json `ep` is current-or-next -> watched = ep - 1
    assert Tracker.watched_of({'ep': 13, 'pos': 0}) == 12
    assert Tracker.watched_of({'ep': 7, 'pos': 100}) == 6
    assert Tracker.watched_of({}) == 0

    # SaveMediaListEntry mutation: CURRENT then COMPLETED at the last episode
    cap = {}

    def gql(q, variables=None, token=None):
        cap['q'], cap['v'] = q, variables
        return {'data': {'SaveMediaListEntry': {
            'progress': variables['p'], 'status': variables['s']}}}
    tr._gql = gql
    assert tr.save_progress(7, 5, total=12)['status'] == 'CURRENT'
    assert cap['v'] == {'id': 7, 'p': 5, 's': 'CURRENT'}
    assert tr.save_progress(7, 12, total=12)['status'] == 'COMPLETED'

    # resolve_media fuzzy + cache (second call must not hit the network)
    media = [{'id': 185542, 'idMal': 60522, 'episodes': 12, 'synonyms': [],
              'title': {'romaji': 'Gaikotsu Kishi-sama, Tadaima Isekai e '
                                  'Odekakechuu II',
                        'english': 'Skeleton Knight II', 'native': None}}]
    tr._gql = lambda q, variables=None, token=None: {
        'data': {'Page': {'media': media}}}
    assert tr.resolve_media('Gaikotsu Kishi Sama Tadaima Isekai E Odekakechuu Ii') \
        == 185542

    def boom(*a, **k):
        raise AssertionError('network hit for a cached title')
    tr._gql = boom
    assert tr.resolve_media('gaikotsu kishi sama tadaima isekai e odekakechuu ii') \
        == 185542

    # new-episode math: aired = next-1 = 9, local watched 6 -> 3 new
    tr._gql = lambda q, variables=None, token=None: {'data': {'Media': {
        'id': variables['id'], 'episodes': 12,
        'title': {'romaji': 'x', 'english': None},
        'mediaListEntry': {'progress': 5},
        'nextAiringEpisode': {'episode': 10, 'airingAt': 1,
                              'timeUntilAiring': -1}}}}
    rows = tr.new_episodes({'Gaikotsu Kishi Sama Tadaima Isekai E Odekakechuu Ii':
                            {'ep': 7, 'pos': 100}})
    assert rows and rows[0]['aired'] == 9 and rows[0]['watched'] == 6 \
        and rows[0]['new'] == 3, rows
    print('PASS tracker progress + episodes')

    # token store
    tr.viewer = lambda token=None: {'id': 1, 'name': 'tester'}
    tr.login('1234', tok='abc')
    assert tr.token() == 'abc'
    tr.logout()
    assert not os.path.exists(cfg.anilist_auth)
    print('PASS tracker token store')


def main():
    test()
    print('TRACKING OK')


if __name__ == '__main__':
    main()
