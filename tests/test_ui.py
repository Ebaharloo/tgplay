#!/usr/bin/env python3
"""test_ui - help panel, recent links, and the plain-prompt fallback."""
import builtins
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp import ui  # noqa: E402


def test_help_lines():
    rl = ui._help_lines({'kind': 'radio', 'opts': ['off', 'all', 'names'],
                         'i': 1, 'help': 'Skip the intro/outro.'}, 40)
    assert any('Skip the intro' in l for l in rl)
    assert any(l.startswith('choices:') and 'all' in l for l in rl), rl
    assert 'current: all' in rl
    assert 'current: on' in ui._help_lines(
        {'kind': 'check', 'val': True, 'help': 'x'}, 40)
    assert 'current: (blank)' in ui._help_lines(
        {'kind': 'text', 'val': '', 'help': 'x'}, 20)
    print('PASS help panel')


def test_recent():
    ui.RECENT = os.path.join(tempfile.mkdtemp(prefix='tgplay-ui-'), 'recent.json')
    for i in range(25):
        ui.recent_add(f'http://x/{i}')
    ui.recent_add('http://x/5')  # dedup -> front
    rs = ui.recent_list()
    assert rs[0] == 'http://x/5' and len(rs) == 20 and rs.count('http://x/5') == 1
    print('PASS recent links')


def test_plain_form():
    ui._curses_ok = lambda: False
    opts = {'f': None, 'e': None, 'a': False, 'cut': None, 'skip': False,
            'skip_toggle': False, 'next': False, 'nowait': False}
    vals = iter(['2', '3-5', '30'])
    _inp = builtins.input
    builtins.input = lambda *a: next(vals)
    try:
        res = ui._plain_form(opts, [{'label': '480P'}, {'label': '720P'}], [])
    finally:
        builtins.input = _inp
    o = res[0]
    assert o['f'] == '720P' and o['e'] == '3-5' and o['cut'] == 30, o
    print('PASS plain form fallback')


def main():
    test_help_lines()
    test_recent()
    test_plain_form()
    print('UI OK')


if __name__ == '__main__':
    main()
