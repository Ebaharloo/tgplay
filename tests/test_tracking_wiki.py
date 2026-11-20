#!/usr/bin/env python3
"""test_tracking_wiki - read-only cast object: cache-first, never raises."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.tracking.wiki import CastSync                       # noqa: E402


class FakeService:
    def cached(self, mal_id=None, title=None):
        return {'names': ['A', 'B']}

    def fetch(self, mal_id=None, title=None):
        raise OSError('wiki down')


def _cfg(tmp):
    return types.SimpleNamespace(progress=f'{tmp}/p.json', conf=tmp,
                                 anilist_auth=f'{tmp}/a.json')


def _sync(tmp, service):
    c = CastSync(_cfg(tmp), http=None, bangumi=None)
    c.service = service
    return c


def test_cached_reads_the_cache(tmp_path):
    assert _sync(tmp_path, FakeService()).cached(mal_id=1) == {'names': ['A', 'B']}


def test_a_dead_wiki_degrades_to_none(tmp_path):
    s = _sync(tmp_path, FakeService())
    assert s.fetch(mal_id=1) is None
    assert s.cached(mal_id=1) == {'names': ['A', 'B']}   # cache still answers


def test_relations_survive_a_down_feed(tmp_path, monkeypatch):
    import tp.simkl_extra as extra
    monkeypatch.setattr(extra.SimklExtra, 'relations',
                        lambda self, sid: (_ for _ in ()).throw(OSError('down')))
    s = _sync(tmp_path, FakeService())
    assert s.relations(123) == []


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
