#!/usr/bin/env python3
"""test_bangumi - Chinese episode titles (search + episodes parsing, mocked)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.bangumi import Bangumi, cjk_title  # noqa: E402


def test_cjk_title():
    assert cjk_title({'alt_titles': [{'name': 'Mushen Ji'},
                                     {'name': '牧神记'}]}) == '牧神记'
    assert cjk_title({}, '遮天') == '遮天'
    assert cjk_title({}, 'Mushen Ji') is None
    print('PASS bangumi cjk_title')


def test_search_episodes():
    b = Bangumi()

    def req(url, data=None):
        if 'search/subjects' in url:
            return {'data': [{'id': 456159, 'name': '牧神记', 'name_cn': '牧神记'}]}
        if 'episodes' in url:
            return {'total': 3, 'data': [
                {'ep': 1, 'name': '天黑别出门', 'name_cn': None},
                {'ep': 2, 'name': '我是霸体', 'name_cn': None},
                {'ep': 3, 'name': '', 'name_cn': '小魔崽子'}]}
        return {}

    b._req = req
    assert b.subject_id('牧神记') == 456159
    assert b.subject_id('牧神记') == 456159      # cached
    eps = b.episodes(456159)
    assert eps == {1: '天黑别出门', 2: '我是霸体', 3: '小魔崽子'}, eps
    print('PASS bangumi search + episodes')


def main():
    test_cjk_title()
    test_search_episodes()
    print('BANGUMI OK')


if __name__ == '__main__':
    main()
