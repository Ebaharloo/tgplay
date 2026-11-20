#!/usr/bin/env python3
"""test_skip - the split skip objects, one concern each.

ChapterReader is stubbed with FakeReader; SkipDecider and the notes are real,
so these pin the decisions a broken probe used to take down with it.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.skip import SkipService, probe_targets  # noqa: E402


class FakeReader:
    """ChapterReader stand-in: chapters per URL, and who was read."""

    def __init__(self, by_url=None):
        self.by_url = dict(by_url or {})
        self.calls = []

    def read(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return list(self.by_url.get(url, []))


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


CHS = [('Intro', 0.0, 90.0), ('Episode', 90.0, 1200.0),
       ('Ending', 1200.0, 1260.0)]


def test_order():
    svc = SkipService(reader=FakeReader({'u': CHS}),
                      ani_skip=FakeAni(['--from-ani']), metadata=FakeMeta())
    flags, note = svc.flags(title='T', ep=1, url='u')
    assert flags == ['--script-opts=skip-op_start=0.0,skip-op_end=90.0,'
                     'skip-ed_start=1200.0,skip-ed_end=1260.0'], flags
    assert note == 'chapters(named) · op 0:00-1:30 · ed 20:00-21:00', note
    # chapters empty -> ani-skip fallback
    svc = SkipService(reader=FakeReader(), ani_skip=FakeAni(['--from-ani']),
                      metadata=FakeMeta())
    flags, note = svc.flags(title='T', ep=1, url='u')
    assert flags == ['--from-ani'] and note.startswith('ani-skip'), note
    # no metadata resolver -> cannot resolve a MAL id -> nothing
    svc = SkipService(reader=FakeReader(), ani_skip=FakeAni(['--from-ani']),
                      metadata=None)
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
    r = FakeReader({'proxy': CHS})
    s = SkipService(reader=r, ani_skip=FakeAni(['--would-be-wrong']))
    flags, note = s.flags(title='x', ep=1, url='origin', url2='proxy')
    assert flags and 'chapters' in note, (flags, note)
    assert r.calls == ['origin', 'proxy'], r.calls


def test_url2_is_not_hit_when_the_origin_answers():
    r = FakeReader({'origin': CHS})
    s = SkipService(reader=r, ani_skip=FakeAni([]))
    flags, note = s.flags(title='x', ep=1, url='origin', url2='proxy')
    assert flags and 'chapters' in note and r.calls == ['origin'], (flags, r.calls)


def test_targets_list_is_tried_in_order():
    r = FakeReader({'proxy': CHS})
    s = SkipService(reader=r, ani_skip=FakeAni([]))
    flags, _note = s.flags(title='x', ep=1,
                           targets=[('origin', {'Referer': 'r'}), ('proxy', None)])
    assert flags and r.calls == ['origin', 'proxy'], (flags, r.calls)


def test_mode_off_short_circuits_before_any_probe():
    r = FakeReader({'u': CHS})
    s = SkipService(reader=r, ani_skip=FakeAni(['--from-ani']),
                    metadata=FakeMeta())
    assert s.flags(title='T', ep=1, url='u', mode='off') == ([], 'off')
    assert r.calls == [], r.calls


def test_toggle_flag_is_appended():
    s = SkipService(reader=FakeReader({'u': CHS}), ani_skip=FakeAni([]))
    flags, _note = s.flags(title='T', ep=1, url='u', toggle=True)
    assert flags == ['--script-opts=skip-op_start=0.0,skip-op_end=90.0,'
                     'skip-ed_start=1200.0,skip-ed_end=1260.0,'
                     'skip-toggle=yes,skip-toggle_key=T'], flags


def test_a_raising_reader_still_tries_the_next_candidate():
    class DeadThenGood(FakeReader):
        def read(self, url, headers=None, timeout=None):
            self.calls.append(url)
            if url == 'origin':
                raise OSError('ffprobe died')
            return list(self.by_url.get(url, []))

    r = DeadThenGood({'proxy': CHS})
    s = SkipService(reader=r, ani_skip=FakeAni(['--would-be-wrong']))
    flags, note = s.flags(title='x', ep=1, url='origin', url2='proxy')
    assert flags and 'chapters' in note, (flags, note)
    assert r.calls == ['origin', 'proxy'], r.calls


def test_probe_targets_origin_first_then_proxy():
    class St:
        url = 'https://cdn/x/1.mkv'
        headers = {'Referer': 'https://site/'}

    assert probe_targets(St()) == [(St.url, St.headers)]
    assert probe_targets(St(), 'http://127.0.0.1:9/1.mkv') == [
        (St.url, St.headers), ('http://127.0.0.1:9/1.mkv', None)]
    # nothing to probe (a prefetched local file): not a fake target
    assert probe_targets(None, 'http://127.0.0.1:9/1.mkv') == []


def main():
    test_order()
    test_notes()
    test_url2_fallback_reads_the_proxy_when_the_origin_hides_chapters()
    test_url2_is_not_hit_when_the_origin_answers()
    test_targets_list_is_tried_in_order()
    test_mode_off_short_circuits_before_any_probe()
    test_toggle_flag_is_appended()
    test_a_raising_reader_still_tries_the_next_candidate()
    test_probe_targets_origin_first_then_proxy()
    print('SKIP OK')


if __name__ == '__main__':
    main()
