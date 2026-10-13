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
    (r'(FAILED|no links|no episodes|^ERROR|^error)', '❌ ', '1;31'),
    (r'^timing:',            '⏱ ',  '90'),
    (r'^search:',            '🔎 ',  '95'),
    (r'^load:',              '📥 ',  '94'),
    (r'^feed:',              '📅 ',  '96'),
    (r'^download:',          '⬇ ',  '32'),
    (r'^mpv:',               '🎞 ',  '92'),
    (r'^link:',              '🔗 ',  '36'),
    (r'^skip:',              '⏭ ',  '35'),
    (r'^skip\[',             '⏭ ',  '35'),
    (r'^next:',              '🔜 ',  '34'),
    (r'^prefetch:',          '⬇ ',  '32'),
    (r'^titles:',            '🏷 ',  '93'),
    (r'^cache:',             '🗃 ',  '33'),
    (r'^>> streaming',       '🎬 ',  '1;32'),
    (r'^>> done',            '🏁 ',  '1'),
    (r'^>>',                 '📡 ',  '92'),
    (r'^track:',             '🔔 ',  '1;36'),
    (r'^sync:',              '🔔 ',  '1;36'),
    (r'^watched:',           '👁 ',  '92'),
    (r'^start:',             '▶ ',   '92'),
    (r'^show:',              '📺 ',  '36'),
    (r'^mal:',               '🅼 ',  '36'),
    (r'^simkl:',             '🆂 ',  '36'),
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


def note(text: str):
    """Record a line to history + logfile WITHOUT printing to the terminal
    (e.g. the log-file path, which the GUI shows but the CLI shouldn't)."""
    HISTORY.append(text)
    if SINK is not None:
        try:
            SINK(text)
        except Exception:
            pass
    if LOGFILE is not None:
        try:
            LOGFILE.write(text + '\n')
        except Exception:
            pass


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


class span:
    """Times a step and prints ONE line on completion (failures too).

        with log.span('search') as s:
            hits = finder.find(q)
            s.result(f'{len(hits)} hit(s)')
        # -> 'search: 12 hit(s) in 1.4s'   (⏱ styled by the rules above)
    """

    def __init__(self, label, echo=True):
        self.label = label
        self.echo = echo
        self.detail = ''
        self._t0 = 0.0

    def result(self, txt):
        self.detail = str(txt or '')
        return self

    def __enter__(self):
        self._t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.echo:
            dur = time.monotonic() - self._t0
            tail = f': {self.detail}' if self.detail else ''
            err = f' FAILED ({exc})' if exc else ''
            cprint(f'{self.label}{tail} in {dur:.1f}s{err}')
        return False                 # never swallow exceptions
