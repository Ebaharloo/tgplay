#!/usr/bin/env python3
"""test_skip - SkipService order: file chapters first, then ani-skip."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.skip import SkipService  # noqa: E402


class FakeResolver:
    def __init__(self, op=None, ed=None, src='named', by_url=None):
        self._op, self._ed, self._src = op, ed, src
        self.by_url = by_url or {}
        self.calls = []

    def resolve(self, url, mode='all', timeout=None, headers=None):
        self.calls.append(url)
        op, ed = self.by_url.get(url, (self._op, self._ed))
        return (op, ed,
                self._src if op else None,
                self._src if ed else None)

    def opts_from(self, op, ed, toggle=False):
        return ['--from-chapters'] if (op or ed) else []


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
    svc = SkipService(resolver=FakeResolver(op=(0, 90), ed=(1200, 1260)),
                      ani_skip=FakeAni(['--from-ani']), metadata=FakeMeta())
    flags, note = svc.flags(title='T', ep=1, url='u')
    assert flags == ['--from-chapters'] and note.startswith('chapters'), note
    # chapters empty -> ani-skip fallback
    svc = SkipService(resolver=FakeResolver(),
                      ani_skip=FakeAni(['--from-ani']), metadata=FakeMeta())
    flags, note = svc.flags(title='T', ep=1, url='u')
    assert flags == ['--from-ani'] and note.startswith('ani-skip'), note
    # no metadata resolver -> cannot resolve a MAL id -> nothing
    svc = SkipService(resolver=FakeResolver(),
                      ani_skip=FakeAni(['--from-ani']), metadata=None)
    flags, note = svc.flags(title='T', ep=1, url='u')
    assert flags == [] and note.startswith('none'), note
    print('PASS skip service order + note')


def test_notes():
    from tp.skip import _chapter_note, _ani_note, _mmss
    assert _mmss(162.667) == '2:42' and _mmss(1300.667) == '21:40'
    n = _chapter_note((0, 162.667), (1198.2, 1300.667), 'named', 'positional')
    assert 'chapters(mixed)' in n and 'op 0:00-2:42' in n \
        and 'ed 19:58-21:40' in n, n
    n2 = _ani_note(['--script-opts=skip-op_start=135.0,skip-op_end=222.0,'
                    'skip-ed_start=1331.1,skip-ed_end=1425.2'])
    assert n2.startswith('ani-skip') and 'op 2:15-3:42' in n2 \
        and 'ed 22:11-23:45' in n2, n2
    print('PASS skip notes formatting')


def test_url2_fallback_reads_the_proxy_when_the_origin_hides_chapters():
    # origin answers but carries no chapters; the same file through the
    # proxy does - skip must not die with the first empty probe
    r = FakeResolver(by_url={'origin': (None, None), 'proxy': ((0, 90), None)})
    s = SkipService(resolver=r, ani_skip=FakeAni(['--would-be-wrong']))
    flags, note = s.flags(title='x', ep=1, url='origin', url2='proxy')
    assert flags == ['--from-chapters'] and 'chapters' in note, (flags, note)
    assert r.calls == ['origin', 'proxy'], r.calls


def test_url2_is_not_hit_when_the_origin_answers():
    r = FakeResolver(op=(43.25, 118.875))
    s = SkipService(resolver=r, ani_skip=FakeAni([]))
    flags, note = s.flags(title='x', ep=1, url='origin', url2='proxy')
    assert flags == ['--from-chapters'] and r.calls == ['origin'], (flags, r.calls)


def main():
    test_order()
    test_notes()
    test_url2_fallback_reads_the_proxy_when_the_origin_hides_chapters()
    test_url2_is_not_hit_when_the_origin_answers()
    print('SKIP OK')


if __name__ == '__main__':
    main()
