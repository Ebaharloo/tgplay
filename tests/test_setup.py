#!/usr/bin/env python3
"""test_setup - the menu remembers the last setup (CLI flags win)."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import setup  # noqa: E402


def test_roundtrip_and_precedence():
    p = os.path.join(tempfile.mkdtemp(prefix='tgplay-setup-'), 'ui.json')
    opts = {'skip': 'names', 'skip_toggle': True, 'next': 0.6, 'nowait': True,
            'cut': 30, 'f': '1080P [x265]'}
    mpv = ['--fullscreen', '--volume', '80']
    d = setup.save(p, opts, mpv)
    assert d['quality'] == 'x265' and d['cut'] == 30 and d['fullscreen'] is True

    saved = setup.load(p)
    o2, m2 = setup.apply({'skip': False, 'skip_toggle': False, 'next': False,
                          'nowait': False, 'cut': None, 'f': None}, [], saved)
    assert o2['skip'] == 'names' and o2['skip_toggle'] and o2['next'] == 0.6
    assert o2['cut'] == 30 and o2['f'] == 'x265', o2
    assert m2 == ['--volume', '80', '--fullscreen'], m2

    # CLI flags win over the saved setup
    o3, m3 = setup.apply({'skip': 'auto', 'skip_toggle': False, 'next': False,
                          'nowait': False, 'cut': 10, 'f': '720'}, ['--x'], saved)
    assert o3['skip'] == 'auto' and o3['cut'] == 10 and o3['f'] == '720', o3
    assert m3 == ['--x', '--fullscreen'], m3   # extra not restored
    print('PASS setup roundtrip + CLI precedence')


def main():
    test_roundtrip_and_precedence()
    print('SETUP OK')


if __name__ == '__main__':
    main()
