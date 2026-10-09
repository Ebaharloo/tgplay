#!/usr/bin/env python3
"""test_history - recent links + search queries for the launcher."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import history  # noqa: E402


class Cfg:
    def __init__(self, p):
        self.progress = p


def test_history():
    cfg = Cfg(os.path.join(tempfile.mkdtemp(prefix='tgplay-hist-'),
                           'progress.json'))
    history.add(cfg, link='https://animegate.ir/anime/x-1')
    history.add(cfg, query='konosuba')
    history.add(cfg, link='https://animex.one/anime/y-2')

    rec = history.recent(cfg)
    # links newest-first, then queries; source detected from the link
    assert rec[0]['url'] == 'https://animex.one/anime/y-2', rec
    assert rec[0]['source'] == 'axp', rec[0]
    link_urls = [r['url'] for r in rec if r['kind'] == 'link']
    assert link_urls == ['https://animex.one/anime/y-2',
                         'https://animegate.ir/anime/x-1'], link_urls
    assert any(r['kind'] == 'query' and r['title'] == 'konosuba' for r in rec)

    # de-dupe: re-adding moves it to the front, no duplicates
    history.add(cfg, link='https://animex.one/anime/y-2')
    links = [r['url'] for r in history.recent(cfg) if r['kind'] == 'link']
    assert links.count('https://animex.one/anime/y-2') == 1, links
    print('PASS history links + queries')


def main():
    test_history()
    print('HISTORY OK')


if __name__ == '__main__':
    main()
