"""tp.log - colour/emoji console logging, owned by the package.

Known line prefixes get an emoji + colour; colour is auto-off when stdout is
not a TTY or NO_COLOR is set. Nothing else in the package should touch
sys.stdout or ANSI codes directly.
"""
import collections
import os
import re
import sys
import time

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
    (r'^show:',              '📺 ',  '36'),
    (r'^mal:',               '🅼 ',  '36'),
]
_RULES = [(re.compile(p), e, s) for p, e, s in _STYLES]
_COLOR = sys.stdout.isatty() and not os.environ.get('NO_COLOR')

real_print = print

# Optional sink (used by the GUI to mirror log lines into a widget), a rolling
# history (so a GUI opened after startup still shows recent lines), and an
# optional log file (so a launcher-started app leaves a trace on disk).
SINK = None
HISTORY = collections.deque(maxlen=1000)
LOGFILE = None


def open_logfile(path: str):
    """Append our log to `path` (launcher-started apps have no terminal)."""
    global LOGFILE
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        LOGFILE = open(path, 'a', buffering=1, encoding='utf-8')
        LOGFILE.write(f'\n===== {time.strftime("%Y-%m-%d %H:%M:%S")} '
                      f'{" ".join(sys.argv[1:])} =====\n')
    except Exception:
        LOGFILE = None
    return LOGFILE


def cprint(*args, **kw):
    line = args[0] if args and isinstance(args[0], str) else None
    plain = line
    ansi = None
    if line is not None:
        for rx, e, s in _RULES:
            if rx.search(line):
                ansi = s
                plain = e + line
                break
        HISTORY.append(plain)
        if SINK is not None:
            try:
                SINK(plain)
            except Exception:
                pass
        if LOGFILE is not None:
            try:
                LOGFILE.write(plain + '\n')
            except Exception:
                pass
    if _COLOR and ansi:
        args = (f'\033[{ansi}m{plain}\033[0m',) + args[1:]
    real_print(*args, **kw)


def style(text, ansi='1;33'):
    """Explicit colour for the rare case a caller needs it (e.g. Ctrl+C bye)."""
    return f'\033[{ansi}m{text}\033[0m' if _COLOR else text
