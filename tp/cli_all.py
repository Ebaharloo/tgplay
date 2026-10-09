"""tp.cli_all - the unified `tgplay` launcher: fill it in, we route it.

One app, one field: type to search AnimeGate + AnimeX together, or paste any
link (animegate / animex / t.me), or `@channel` for a Telegram channel. The
chosen target is handed to the matching per-source CLI, which owns the
provider, menus and playback. This module is only the front door - the OOP
split keeps each source's logic in its own provider/CLI.
"""
import re
import sys
from typing import List, Optional, Tuple

ALL_HELP = """\
tgplay - one launcher for every source.

  tgplay                  one field: search (AnimeGate + AnimeX) or paste a link
  tgplay agp|axp|tg|tgp …  run that source directly (same as its own command)
  tgplay <url>            auto-detect the source from the link
  tgplay simkl login      connect your Simkl account (watch-list sync + feed)
  tgplay simkl status|library|logout
  tgplay simkl setup      one-time app registration (maintainer)

  One field does it all:
    • type a title      -> results from AnimeGate AND AnimeX, pick one
    • paste a link       -> animegate.ir / animex.one / t.me links
    • @channel           -> browse a Telegram channel

  The per-source commands (agp, axp, tg, tgp) still work on their own.
"""


def route(text: str) -> Optional[Tuple[str, str]]:
    """Route one input -> (source_id, target), or None if it's a search query.

    Handles: axp:<slug>, animegate/animex links, t.me links (file vs channel),
    and `@channel`.
    """
    t = (text or '').strip()
    if not t:
        return None
    tl = t.lower()
    if tl.startswith('axp:'):
        return ('axp', t)
    if 'animegate' in tl:
        return ('agp', t)
    if 'animex' in tl:
        return ('axp', t)
    m = re.search(r't\.me/([A-Za-z0-9_]+)(?:/(\d+))?', t)
    if m:
        if m.group(2):
            return ('tg', t)                 # a single-file message link
        return ('tgp', m.group(1))           # a channel link
    if t.startswith('@'):
        return ('tgp', t)
    return None


def detect(url: str) -> Optional[str]:
    """The source id for a link (else None)."""
    r = route(url)
    return r[0] if r else None


def dispatch(src: str, target: Optional[str], extra=()) -> int:
    """Run the per-source CLI with the chosen target."""
    if src == 'search':
        src = detect(target) or 'agp'
    args = list(extra)
    if target:
        if src == 'tg' and 't.me/' not in target and ' ' in target:
            args += ['--menu'] + target.split()
        else:
            args += ['--menu', target]
    if src == 'agp':
        from .cli import main
        return main(args) or 0
    if src == 'axp':
        from .cli_animex import main_axp
        return main_axp(args) or 0
    if src == 'tgp':
        from .cli_telegram import main_tgp
        return main_tgp(args) or 0
    if src == 'tg':
        from .cli_telegram import main_tg
        return main_tg(args or ['--menu']) or 0
    return 2


def _choose_plain() -> Optional[Tuple[str, str]]:
    try:
        text = input('search, link, or @channel: ').strip()
    except EOFError:
        return None
    if not text:
        return None
    r = route(text)
    if r:
        return r
    try:
        q = input('search animegate + animex [enter]: ').strip() or text
    except EOFError:
        return None
    from .search import search_all
    got = search_all(q, sources=('agp', 'axp'))
    for i, item in enumerate(got, 1):
        print(f'  {i}) [{item["source"]}] {item["title"]}')
    if not got:
        return None
    try:
        v = input('pick [1]: ').strip()
    except EOFError:
        return None
    if v.isdigit() and 1 <= int(v) <= len(got):
        it = got[int(v) - 1]
        return (it['source'], it['url'])
    return None


def _simkl_cmd(args: List[str]) -> int:
    from .config import Config
    from .http import HttpClient
    from .simkl_account import SimklAccount
    cfg = Config().ensure()
    acc = SimklAccount(cfg, HttpClient())
    cmd = (args[0] if args else 'status').lower()
    if cmd in ('setup', 'register'):
        cid = next((a for a in args[1:] if not a.startswith('-')), None)
        if cid:
            from .simkl import save_client_id
            save_client_id(cid)
            print('simkl: client_id saved — users can now just run '
                  '`tgplay simkl login`')
            return 0
        print('simkl: one-time app registration (maintainer, once):')
        print('  1) https://simkl.com/settings/developer/  -> new app')
        print('  2) client type: "TV, devices & command line" (no redirect)')
        print('  3) scope: media:read media:write')
        print('  4) copy the client_id, then either:')
        print('       agp simkl <CLIENT_ID>')
        print('     or set BUILTIN_CLIENT_ID in tp/simkl_account.py to ship it')
        print('  Users then only run:  tgplay simkl login')
        return 0
    if cmd == 'login':
        return 0 if acc.login() else 1
    if cmd == 'logout':
        acc.logout()
        return 0
    if cmd in ('library', 'list'):
        rows = acc.library()
        if not rows:
            print('simkl: library empty, or not connected '
                  '(run: tgplay simkl login)')
            return 0
        for e in rows:
            nx = f"ep {e['next_ep']}" if e.get('next_ep') else 'caught up'
            print(f"  {str(e['status']):<11} {e['watched']}/{e['total']:<4} "
                  f"{nx:<10} {e['title']}")
        return 0
    if acc.logged_in():
        who = acc.user()
        print(f"simkl: connected{(' as ' + who) if who else ''}")
        rows = acc.up_next()
        for e in rows:
            print(f"  up next: {e['title']}  ->  ep {e['next_ep']}")
        if not rows:
            print('  all caught up')
    else:
        print('simkl: not connected (run: tgplay simkl login)')
    return 0


def main_all(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ('-h', '--help') for a in argv):
        print(ALL_HELP)
        return 0

    if argv and argv[0].lower() == 'simkl':
        return _simkl_cmd(argv[1:])

    # explicit source: `tgplay axp <args...>`
    if argv and argv[0].lower() in ('agp', 'axp', 'tg', 'tgp'):
        return dispatch(argv[0].lower(), None, argv[1:])

    flags = [a for a in argv if a.startswith('-')]
    pos = [a for a in argv if not a.startswith('-')]

    # a link given -> route it
    if pos:
        r = route(pos[0])
        if r:
            return dispatch(r[0], r[1], flags)
        print(f'tgplay: could not tell the source of "{pos[0]}"')
        print(ALL_HELP)
        return 2

    # interactive: one window (search + episodes/options in place)
    from .cli import _pick_gui
    from . import ui
    force_curses = '--curses' in argv
    gui = _pick_gui()
    if (not force_curses and gui.available()
            and str(getattr(gui, '__name__', '')).endswith('gui_qt')):
        from .config import Config
        from .http import HttpClient
        from .session import open_session
        from . import setup
        from . import gui_all
        cfg = Config().ensure()
        http = HttpClient()

        def loader(src, target):
            o = {'a': False, 'skip': False, 'skip_toggle': False, 'e': None,
                 'f': None, 'cut': None, 'next': False, 'nowait': False}
            o, m = setup.apply(o, [], setup.load(cfg.ui, src))
            return open_session(src, target, cfg, http, o, m)

        gui_all.app(loader, cfg=cfg)
        return 0

    res = None
    if not force_curses and gui.available() and hasattr(gui, 'launcher'):
        res = gui.launcher()          # Tk fallback picker (Qt uses gui_all above)
    if res is None and ui.available():
        res = _choose_plain()         # terminal chooser (also for --curses)
    if not res:
        if not ui.available() and not (gui.available()
                                       and hasattr(gui, 'launcher')):
            print(ALL_HELP)
        return 0
    return dispatch(res[0], res[1], flags)
