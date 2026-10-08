"""tp.log - colour/emoji console logging, owned by the package.

Known line prefixes get an emoji + colour; colour is auto-off when stdout is
not a TTY or NO_COLOR is set. Nothing else in the package should touch
sys.stdout or ANSI codes directly.
"""
import os
import re
import sys

_STYLES = [
    (r'(FAILED|no links|no episodes|^ERROR)', '❌ ', '1;31'),
    (r'^timing:',            '⏱ ',  '90'),
    (r'^link:',              '🔗 ',  '36'),
    (r'^skip:',              '⏭ ',  '35'),
    (r'^next:',              '🔜 ',  '34'),
    (r'^prefetch:',          '⬇ ',  '32'),
    (r'^cache:',             '🗃 ',  '33'),
    (r'^>> streaming',       '🎬 ',  '1;32'),
    (r'^>> done',            '🏁 ',  '1'),
    (r'^track:',             '🔔 ',  '1;36'),
]
_RULES = [(re.compile(p), e, s) for p, e, s in _STYLES]
_COLOR = sys.stdout.isatty() and not os.environ.get('NO_COLOR')

real_print = print


def cprint(*args, **kw):
    if _COLOR and args and isinstance(args[0], str):
        line = args[0]
        for rx, emoji, ansi in _RULES:
            if rx.search(line):
                args = (f'\033[{ansi}m{emoji}{line}\033[0m',) + args[1:]
                break
    real_print(*args, **kw)


def style(text, ansi='1;33'):
    """Explicit colour for the rare case a caller needs it (e.g. Ctrl+C bye)."""
    return f'\033[{ansi}m{text}\033[0m' if _COLOR else text
