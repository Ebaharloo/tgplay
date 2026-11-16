#!/usr/bin/env python3
"""test_cache - own test model for the download cache (tp.cache)."""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.cache import Cache  # noqa: E402


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


def main():
    test_cache_report_clean()
    print('CACHE OK')


if __name__ == '__main__':
    main()
