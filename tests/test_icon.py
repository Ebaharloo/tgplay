#!/usr/bin/env python3
"""test_icon - packaged assets exist and install() writes a launcher + icons."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import icon  # noqa: E402


def test_assets():
    assert os.path.exists(icon.svg()), icon.svg()
    for s in (16, 32, 48, 256):
        p = icon.png(s)
        assert p and os.path.exists(p), (s, p)
    assert os.path.exists(os.path.join(icon.ASSETS, 'tgplay-256.png'))
    print('PASS icon assets present')


def test_install():
    d = tempfile.mkdtemp()
    old = os.environ.get('XDG_DATA_HOME')
    os.environ['XDG_DATA_HOME'] = d
    try:
        written = icon.install(exec_path='/usr/bin/agp-test')
        desk = os.path.join(d, 'applications', 'tgplay.desktop')
        assert desk in written
        txt = open(desk).read()
        assert 'Exec=/usr/bin/agp-test' in txt, txt
        assert 'Icon=tgplay' in txt, txt
        assert 'StartupWMClass=tgplay' in txt, txt
        for s in (16, 256):
            p = os.path.join(d, 'icons', 'hicolor', f'{s}x{s}', 'apps',
                             'tgplay.png')
            assert os.path.exists(p), p
        p = os.path.join(d, 'icons', 'hicolor', 'scalable', 'apps',
                         'tgplay.svg')
        assert os.path.exists(p), p
        print('PASS icon install (desktop + hicolor)')
    finally:
        if old is None:
            os.environ.pop('XDG_DATA_HOME', None)
        else:
            os.environ['XDG_DATA_HOME'] = old


def main():
    test_assets()
    test_install()
    print('ICON OK')


if __name__ == '__main__':
    main()
