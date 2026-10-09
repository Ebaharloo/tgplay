#!/usr/bin/env python3
"""test_cli_all - the unified launcher: input routing + source dispatch."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tp import cli_all  # noqa: E402
import tp.cli as cli  # noqa: E402
import tp.cli_animex as ax  # noqa: E402
import tp.cli_telegram as tg  # noqa: E402


def test_route():
    assert cli_all.route('https://animegate.ir/anime/x-1') == \
        ('agp', 'https://animegate.ir/anime/x-1')
    assert cli_all.route('https://animex.one/anime/y-2')[0] == 'axp'
    assert cli_all.route('axp:foo-1') == ('axp', 'axp:foo-1')
    assert cli_all.route('https://t.me/chan/123') == ('tg', 'https://t.me/chan/123')
    assert cli_all.route('https://t.me/mychan') == ('tgp', 'mychan')
    assert cli_all.route('@mychan') == ('tgp', '@mychan')
    assert cli_all.route('konosuba') is None            # a query -> search
    assert cli_all.route('') is None
    assert cli_all.detect('https://animex.one/anime/y') == 'axp'
    print('PASS route/detect')


def test_dispatch_calls_right_main():
    calls = []
    old = (cli.main, ax.main_axp, tg.main_tgp, tg.main_tg)
    cli.main = lambda a=None: calls.append(('agp', a)) or 0
    ax.main_axp = lambda a=None: calls.append(('axp', a)) or 0
    tg.main_tgp = lambda a=None: calls.append(('tgp', a)) or 0
    tg.main_tg = lambda a=None: calls.append(('tg', a)) or 0
    try:
        cli_all.dispatch('agp', 'https://animegate.ir/anime/x')
        cli_all.dispatch('axp', 'axp:foo')
        cli_all.dispatch('tgp', '@chan')
        cli_all.dispatch('tg', 'https://t.me/c/5')
        cli_all.dispatch('tg', 'chan 5')                 # channel msgid -> split
        cli_all.dispatch('search', 'https://animex.one/anime/y')  # -> axp
    finally:
        cli.main, ax.main_axp, tg.main_tgp, tg.main_tg = old
    assert calls[0] == ('agp', ['--menu', 'https://animegate.ir/anime/x']), calls[0]
    assert calls[1] == ('axp', ['--menu', 'axp:foo']), calls[1]
    assert calls[2] == ('tgp', ['--menu', '@chan']), calls[2]
    assert calls[3] == ('tg', ['--menu', 'https://t.me/c/5']), calls[3]
    assert calls[4] == ('tg', ['--menu', 'chan', '5']), calls[4]
    assert calls[5][0] == 'axp', calls[5]
    print('PASS dispatch routing')


def main():
    test_route()
    test_dispatch_calls_right_main()
    print('CLI_ALL OK')


if __name__ == '__main__':
    main()
