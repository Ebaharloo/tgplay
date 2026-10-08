#!/usr/bin/env python3
"""test_quality_cache - quality-from-filename grouping + cache report/clean."""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import quality    # noqa: E402
from tp.cache import Cache  # noqa: E402


def test_quality():
    assert quality.parse_quality('x 480p y') == '480p'
    assert quality.parse_quality('x 1080P y') == '1080p'
    assert quality.parse_quality('movie 4K') == '2160p'
    assert quality.parse_quality('no tag here') is None
    names = ['BTTH - S5 E213 [Eng-Sub] 480p @S.mkv',
             'BTTH - S5 E213 [Eng-Sub] 1080p @S.mkv',
             'BTTH - S5 E213 [Eng-Sub] 4K @S.mkv']
    qs, byq = quality.group(names)
    assert qs == ['480p', '1080p', '2160p'], qs
    assert len(byq['1080p']) == 1 and byq['1080p'][0].endswith('1080p @S.mkv')
    # a single quality is not a group (caller keeps the flat list)
    assert quality.group(['a 720p.mkv', 'b 720p.mkv']) == ([], {})
    assert quality.strip_quality('BTTH - S5 E213 480p x.mkv') \
        == 'BTTH - S5 E213 x.mkv'
    print('PASS quality parsing + grouping')


def test_cache_report_clean():
    d = tempfile.mkdtemp(prefix='tgplay-cc-')
    c = Cache(d, budget=10 ** 9)
    done = c.path('done.mkv')
    open(done, 'wb').write(b'x' * 1000)
    os.utime(done, (time.time() - 5 * 86400,) * 2)
    part = c.path('part.mkv') + '.part'
    open(part, 'wb').write(b'y' * 500)
    os.utime(part, (time.time() - 1 * 86400,) * 2)

    rows = {r['name']: r for r in c.report()}
    assert rows['done.mkv']['partial'] is False
    assert rows['part.mkv']['partial'] is True

    # older-than-3-days cleanup removes the finished 5-day file, keeps the
    # 1-day partial (a viewer may continue it later)
    assert c.clean(days=3) >= 1
    assert not os.path.exists(done) and os.path.exists(part)

    # --keep-partial semantics: clean-all still spares unfinished downloads
    assert c.clean(all=True, include_partials=False) == 0
    assert os.path.exists(part)
    assert c.clean(all=True) >= 1
    assert not os.path.exists(part)
    print('PASS cache report + age cleanup')


def main():
    test_quality()
    test_cache_report_clean()
    print('QUALITY+CACHE OK')


if __name__ == '__main__':
    main()
