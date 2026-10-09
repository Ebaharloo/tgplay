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


def test_namespaced_per_source():
    import json
    p = os.path.join(tempfile.mkdtemp(prefix='tgplay-setup-'), 'ui.json')
    setup.save(p, {'skip': 'all', 'f': '720'}, [], 'agp')
    setup.save(p, {'skip': 'off', 'f': 'nero (dub+sub)'}, [], 'axp')
    assert setup.load(p, 'agp')['quality'] == '720'
    assert setup.load(p, 'axp')['quality'] == 'nero (dub+sub)'
    # legacy flat file: readable as agp, migrated on next save
    flat = os.path.join(tempfile.mkdtemp(prefix='tgplay-setup-'), 'ui.json')
    json.dump({'skip': 'all', 'quality': 'DUB · nero'}, open(flat, 'w'))
    assert setup.load(flat, 'agp')['quality'] == 'DUB · nero'
    assert setup.load(flat, 'axp') == {}
    setup.save(flat, {'f': '480'}, [], 'axp')
    all_ = json.load(open(flat))
    assert all_['agp']['quality'] == 'DUB · nero'
    assert all_['axp']['quality'] == '480'
    print('PASS setup namespaced per source + legacy migration')


def test_animegate_tolerates_unknown_quality():
    from tp.providers.animegate import AnimeGateProvider
    p = AnimeGateProvider('https://animegate.ir/anime/x-1')
    p.groups = [{'id': 1, 'label': '480P هاردساب', 'data': []},
                {'id': 2, 'label': '720P هاردساب', 'data': []}]
    p.select('DUB · nero')          # a leaked AnimeX label -> fall back
    assert p.group['id'] == 1, p.group
    print('PASS animegate tolerates an unknown quality')


def main():
    test_roundtrip_and_precedence()
    test_namespaced_per_source()
    test_animegate_tolerates_unknown_quality()
    print('SETUP OK')


if __name__ == '__main__':
    main()
