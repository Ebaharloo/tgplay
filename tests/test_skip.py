#!/usr/bin/env python3
"""test_skip - SkipService order: file chapters first, then ani-skip."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.skip import SkipService  # noqa: E402


class FakeResolver:
    def __init__(self, flags):
        self._f = flags

    def flags(self, url, mode='all', toggle=False, timeout=None):
        return list(self._f)


class FakeAni:
    def __init__(self, flags):
        self._f = flags

    def available(self):
        return True

    def flags(self, mal, ep, toggle=False):
        return list(self._f)


class FakeMeta:
    def resolve_mal(self, title, ask=False):
        return 123


def test_order():
    svc = SkipService(resolver=FakeResolver(['--from-chapters']),
                      ani_skip=FakeAni(['--from-ani']), metadata=FakeMeta())
    assert svc.flags(title='T', ep=1, url='u') == ['--from-chapters']
    # chapters empty -> ani-skip fallback
    svc = SkipService(resolver=FakeResolver([]),
                      ani_skip=FakeAni(['--from-ani']), metadata=FakeMeta())
    assert svc.flags(title='T', ep=1, url='u') == ['--from-ani']
    # no metadata resolver -> cannot resolve a MAL id -> nothing
    svc = SkipService(resolver=FakeResolver([]),
                      ani_skip=FakeAni(['--from-ani']), metadata=None)
    assert svc.flags(title='T', ep=1, url='u') == []
    print('PASS skip service order')


def main():
    test_order()
    print('SKIP OK')


if __name__ == '__main__':
    main()
