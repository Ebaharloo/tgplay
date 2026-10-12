"""tp.ui - interactive option editor (curses form + plain-prompt fallback).

One screen lists every option (move up/down, change any earlier choice), with a
key-hint line at the bottom and a help panel for the highlighted option. The
link chooser uses the same style. Non-TTY callers are never prompted.
"""
import json
import os
import sys
import textwrap
from typing import List, Optional

CONF = os.path.expanduser('~/.config/tgp')
RECENT = os.path.join(CONF, 'recent.json')
HINT = ' Up/Down move   Space/Enter change or type   s start   q cancel '


def available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _curses_ok() -> bool:
    if not available():
        return False
    try:
        import curses  # noqa: F401
        return True
    except Exception:
        return False


# --- recent links -----------------------------------------------------------
def recent_list() -> List[str]:
    try:
        return [u for u in json.load(open(RECENT)) if isinstance(u, str)]
    except Exception:
        return []


def recent_add(url: str):
    if not url:
        return
    rs = [u for u in recent_list() if u != url]
    rs.insert(0, url)
    os.makedirs(os.path.dirname(RECENT), exist_ok=True)
    json.dump(rs[:20], open(RECENT, 'w'))


# --- key decoding -----------------------------------------------------------
def _read_key(stdscr):
    ch = stdscr.getch()
    if ch != 27:
        return ch
    import curses
    stdscr.timeout(25)
    seq = []
    for _ in range(2):
        n = stdscr.getch()
        if n == -1:
            break
        seq.append(n)
    stdscr.timeout(-1)
    return {(ord('['), ord('A')): curses.KEY_UP,
            (ord('['), ord('B')): curses.KEY_DOWN,
            (ord('['), ord('C')): curses.KEY_RIGHT,
            (ord('['), ord('D')): curses.KEY_LEFT,
            (ord('O'), ord('A')): curses.KEY_UP,
            (ord('O'), ord('B')): curses.KEY_DOWN}.get(tuple(seq), 27)


def choose_url() -> Optional[str]:
    if not _curses_ok():
        if not sys.stdin.isatty():
            return None
        try:
            return input('animegate link: ').strip() or None
        except EOFError:
            return None
    import curses
    items = [(u, u) for u in recent_list()[:12]]
    items.append(('__new__', '✎  Enter a new link…'))

    def run(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        try:
            curses.flushinp()  # drop stale typeahead (no auto-advance)
        except Exception:
            pass
        cur = 0
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            stdscr.addnstr(0, 0, ' agp · which anime?  (Enter select, q quit)',
                           max(0, w - 1), curses.A_REVERSE)
            for i, (_t, label) in enumerate(items):
                row = 2 + i
                if row >= h - 2:
                    break
                attr = curses.A_REVERSE if i == cur else curses.A_NORMAL
                stdscr.addnstr(row, 1, ('▶ ' if i == cur else '  ') + label,
                               max(0, w - 2), attr)
            stdscr.addnstr(h - 1, 0, ' Up/Down move   Enter select   q cancel ',
                           max(0, w - 1), curses.A_DIM)
            stdscr.refresh()
            ch = _read_key(stdscr)
            if ch in (ord('q'), 27):
                return None
            if ch in (curses.KEY_UP, ord('k')):
                cur = (cur - 1) % len(items)
            elif ch in (curses.KEY_DOWN, ord('j')):
                cur = (cur + 1) % len(items)
            elif ch in (curses.KEY_ENTER, 10, 13, ord(' ')):
                tag = items[cur][0]
                if tag != '__new__':
                    return tag
                curses.curs_set(1)
                curses.echo()
                try:
                    stdscr.move(2 + cur, 1)
                    stdscr.clrtoeol()
                    stdscr.addnstr(2 + cur, 1, 'Link:  ', max(0, w - 2))
                    stdscr.move(2 + cur, 7)
                    stdscr.refresh()
                    v = stdscr.getstr(2 + cur, 7, 300).decode(
                        'utf-8', 'replace').strip()
                except Exception:
                    v = ''
                finally:
                    curses.noecho()
                    curses.curs_set(0)
                if v:
                    return v
    try:
        return curses.wrapper(run)
    except Exception:
        return None


# --- options form -----------------------------------------------------------
def prompt(text: str) -> Optional[str]:
    """Single-line text entry (curses if possible, else input())."""
    if not available():
        try:
            return input(text + ': ').strip() or None
        except EOFError:
            return None
    import curses

    def run(stdscr):
        curses.curs_set(1)
        curses.echo()
        try:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            stdscr.addnstr(0, 0, ' tgplay · ' + text, max(0, w - 1),
                           curses.A_REVERSE)
            stdscr.addnstr(2, 2, text + ': ', max(0, w - 3))
            stdscr.move(2, 3 + len(text))
            stdscr.refresh()
            v = stdscr.getstr(2, 3 + len(text), 300).decode('utf-8', 'replace')
        except Exception:
            v = ''
        finally:
            curses.noecho()
            curses.curs_set(0)
        return v.strip() or None
    try:
        return curses.wrapper(run)
    except Exception:
        return None


def pick_start(items, resume=None):
    """Show the whole list; Enter = play from the highlighted item to the end,
    'a' = all, 'q' = cancel. Returns the chosen keys (or None)."""
    nums = sorted(items)
    if not nums:
        return []
    if not _curses_ok():
        print(f'{len(nums)} items: {nums[0]}..{nums[-1]}')
        try:
            v = input(f'play from [{resume or nums[0]}] '
                      '(a=all, q=quit): ').strip().lower()
        except EOFError:
            return None
        if v == 'q':
            return None
        if v in ('', 'a'):
            start = resume if resume in items else nums[0]
        elif v.isdigit() and int(v) in items:
            start = int(v)
        else:
            return nums
        return [n for n in nums if n >= start]
    import curses

    def run(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        try:
            curses.flushinp()  # drop stale typeahead (no auto-advance)
        except Exception:
            pass
        try:
            curses.set_escdelay(25)
        except Exception:
            pass
        cur = nums.index(resume) if resume in items else 0
        top = 0
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            view = max(1, h - 3)
            if cur < top:
                top = cur
            if cur >= top + view:
                top = cur - view + 1
            head = f' {len(nums)} episodes   Enter = from here   o = only this   a = all   q = quit '
            stdscr.addnstr(0, 0, head[:max(0, w - 1)], max(0, w - 1),
                           curses.A_REVERSE)
            for i in range(top, min(top + view, len(nums))):
                n = nums[i]
                tag = '   <resume>' if n == resume else ''
                line = f'{n:>5}  {items[n]}{tag}'
                attr = curses.A_REVERSE if i == cur else curses.A_NORMAL
                stdscr.addnstr(2 + (i - top), 1, line[:max(0, w - 2)],
                               max(0, w - 2), attr)
            stdscr.addnstr(
                h - 1, 0,
                ' Up/Down scroll   Enter start-here   o only-this   a all   q cancel '[
                    :max(0, w - 1)], max(0, w - 1), curses.A_DIM)
            stdscr.refresh()
            ch = _read_key(stdscr)
            if ch in (ord('q'), 27):
                return None
            if ch == ord('a'):
                return nums
            if ch == ord('o'):
                return [nums[cur]]
            if ch in (curses.KEY_UP, ord('k')):
                cur = max(0, cur - 1)
            elif ch in (curses.KEY_DOWN, ord('j')):
                cur = min(len(nums) - 1, cur + 1)
            elif ch == curses.KEY_PPAGE:
                cur = max(0, cur - view)
            elif ch == curses.KEY_NPAGE:
                cur = min(len(nums) - 1, cur + view)
            elif ch in (curses.KEY_ENTER, 10, 13):
                return [n for n in nums if n >= nums[cur]]
    try:
        return curses.wrapper(run)
    except Exception:
        return None


def _help_lines(f, width) -> List[str]:
    out = textwrap.wrap(f.get('help', ''), width) or ['']
    if f['kind'] == 'radio':
        out += textwrap.wrap('choices: ' + ' · '.join(str(o) for o in f['opts']),
                             width) or []
        out += ['current: ' + str(f['opts'][f['i']])]
    elif f['kind'] == 'check':
        out += ['current: ' + ('on' if f['val'] else 'off')]
    else:
        out += ['current: ' + (f['val'] or '(blank)')]
    return out


def gather(opts, groups, mpv, show_eps=True, audio=False):
    """Show the option boxes; return updated (opts, mpv), or None if cancelled."""
    if _curses_ok():
        try:
            return _curses_form(opts, groups, mpv, show_eps, audio)
        except Exception:
            pass
    return _plain_form(opts, groups, mpv, show_eps, audio)


def _curses_form(opts, groups, mpv, show_eps=True, audio=False):
    """The curses form, rendered from the ONE shared spec (tp.options)."""
    import curses
    from .options import form_fields, form_result

    def build_fields():
        fields = form_fields(groups=[str(g['label']) for g in groups],
                             audio=audio, show_eps=show_eps,
                             opts=opts, mpv=mpv)
        for f in fields:              # adapt to the curses renderer's kinds
            if f['kind'] == 'choice':
                f['kind'] = 'radio'
                f['opts'] = f['choices']
            elif f['kind'] == 'flag':
                f['kind'] = 'check'
        return fields

    fields = build_fields()

    def render(f, sel):
        if f['kind'] == 'check':
            body = f"[{'x' if f['val'] else ' '}] {f['label']}"
        elif f['kind'] == 'radio':
            body = f"< {f['opts'][f['i']]} >   {f['label']}"
        else:
            body = f"{f['label']}:  [ {f['val']} ]"
        return ('▶ ' if sel else '  ') + body

    def change(f, d):
        if f['kind'] == 'radio':
            f['i'] = (f['i'] + d) % len(f['opts'])
        elif f['kind'] == 'check':
            f['val'] = not f['val']

    def edit(stdscr, f, row):
        prompt = f"{f['label']}:  "
        curses.curs_set(1)
        curses.echo()
        try:
            stdscr.move(row, 2)
            stdscr.clrtoeol()
            stdscr.addnstr(row, 2, prompt + f['val'], 200)
            stdscr.move(row, 2 + len(prompt))
            stdscr.refresh()
            f['val'] = stdscr.getstr(row, 2 + len(prompt), 80).decode(
                'utf-8', 'replace')
        except Exception:
            pass
        finally:
            curses.noecho()
            curses.curs_set(0)

    def run(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)
        try:
            curses.flushinp()  # drop stale typeahead (no auto-advance)
        except Exception:
            pass
        try:
            curses.set_escdelay(25)
        except Exception:
            pass
        cur = 0
        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            stdscr.addnstr(0, 0, ' agp · set options (s = start, q = cancel)',
                           max(0, w - 1), curses.A_REVERSE)
            for i, f in enumerate(fields):
                row = 2 + i
                if row >= h - 3:
                    break
                attr = curses.A_REVERSE if i == cur else curses.A_NORMAL
                stdscr.addnstr(row, 1, render(f, i == cur), max(0, w - 2), attr)
            hy = 2 + len(fields)
            if hy < h - 2:
                stdscr.addnstr(hy, 1, '─' * max(0, w - 2), max(0, w - 2),
                               curses.A_DIM)
                for j, ln in enumerate(_help_lines(fields[cur], max(10, w - 4))):
                    r = hy + 1 + j
                    if r >= h - 2:
                        break
                    stdscr.addnstr(r, 2, ln, max(0, w - 3))
            stdscr.addnstr(h - 1, 0, HINT[:max(0, w - 1)], max(0, w - 1),
                           curses.A_DIM)
            stdscr.refresh()
            ch = _read_key(stdscr)
            if ch in (ord('q'), 27):
                return None
            if ch in (curses.KEY_UP, ord('k')):
                cur = (cur - 1) % len(fields)
            elif ch in (curses.KEY_DOWN, ord('j')):
                cur = (cur + 1) % len(fields)
            elif ch in (curses.KEY_LEFT, ord('h')):
                if fields[cur]['kind'] != 'text':
                    change(fields[cur], -1)
            elif ch in (curses.KEY_RIGHT, ord('l')):
                if fields[cur]['kind'] != 'text':
                    change(fields[cur], 1)
            elif ch in (curses.KEY_ENTER, 10, 13, ord(' ')):
                f = fields[cur]
                if f['kind'] == 'text':
                    edit(stdscr, f, 2 + cur)
                else:
                    change(f, 1)
            elif ch == ord('s'):
                return fields

    fs = curses.wrapper(run)
    if fs is None:
        return None
    return form_result(fs, opts, mpv)       # shared model: nothing gets lost


def _plain_form(opts, groups, mpv, show_eps=True, audio=False):
    labels = [str(g['label']) for g in groups]
    if labels:
        print('Server:' if audio else 'Quality:')
        for i, l in enumerate(labels, 1):
            print(f'  {i}) {l}')
        try:
            q = input('server [1]: ' if audio else 'quality [1]: ').strip()
        except EOFError:
            return None
        if q.isdigit() and 1 <= int(q) <= len(labels):
            opts['f'] = labels[int(q) - 1]
    if audio:
        amodes = ['dub', 'sub', 'auto']
        cur = opts.get('audio') if opts.get('audio') in amodes else 'dub'
        try:
            a = input(f'audio dub/sub/auto [{cur}]: ').strip().lower()
        except EOFError:
            return None
        opts['audio'] = a if a in amodes else cur
    try:
        if show_eps:
            e = input('eps [a|2-5,9]: ').strip().lower()
            opts['a'], opts['e'] = (True, None) if e in ('', 'a') else (False, e)
        c = input('cut last N sec [blank]: ').strip()
    except EOFError:
        return None
    opts['cut'] = int(c) if c.isdigit() else None
    return opts, mpv
