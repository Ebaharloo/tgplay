"""tp.cli - argument parsing and wiring; the `agp` entry point.

`parse()` builds the same flag set the original `opts.py` did; `main()` wires
the services together and runs the Playlist. No globals.
"""
import os
import sys
import threading
from typing import List, Optional, Tuple

from .cache import Cache                 # `agp cache` command
from .config import Config
from .http import HttpClient
from . import episodes as epmod
from . import setup
from . import log

HELP = """\
agp (tgplay) - stream animegate.ir mkv links, no downloads.

  agp <anime-url> [-e 1-12] [-q 720] [-a] [--skip] [--cut 30] [--next] [mpv flags]

  -e RANGE        episodes: 1-12, 2-5,9        (default: ask / resume)
  -a              all episodes
  -q/-f SUB       quality substring, e.g. -q 720
  --skip[=MODE]   skip intro/outro: all (default) | names | auto
  --skip-toggle   let T in mpv turn skipping off
  --next[=P]      pre-download the next ep once P% played (default 60)
  --nowait        start that download at the cut point (needs --cut)
  --cut N         stop N seconds before each episode's end
  --start N       start each episode at N seconds
  --no-sync       don't push watch progress to Simkl/AniList
  any other --flag goes to mpv verbatim

  agp --menu                open a menu: a native desktop window (Qt/PySide6
                            when available, else Tkinter) when a display is
                            present, else the terminal menu
  --gui / --curses          force the desktop window / the terminal menu
  agp cache [clean [--days N]]  show / clean the download cache
  agp icon                  install the app icon + launcher entry
  agp simkl <CLIENT_ID>     set the Simkl key for episode titles (donghua)
  agp login <CLIENT_ID> | logout | sync [--dry] | new | tracking
                            AniList progress sync + new-episode notices
  Telegram: use ./tg (one file) and ./tgp (channel); log in with `tgp login`.
"""


def _pick_gui():
    """Prefer the native Qt window (follows KDE/GNOME theming), then Tkinter."""
    try:
        from . import gui_qt
        if gui_qt.available():
            return gui_qt
    except Exception:
        pass
    from . import gui
    return gui


def _notify(tracker):
    try:
        tracker.notify_new()
    except Exception:
        pass


def _resume_ep(cfg, title):
    import json as _j
    try:
        d = _j.load(open(cfg.progress))
        e = d.get(title, {})
        return int(e.get('ep')) if e.get('ep') else None
    except Exception:
        return None


def _resume_pos(cfg, title):
    import json as _j
    try:
        d = _j.load(open(cfg.progress))
        return int(d.get(title, {}).get('pos') or 0)
    except Exception:
        return 0


def _links_path(cfg):
    return os.path.join(os.path.dirname(cfg.progress), 'links.json')


def _link_get(cfg, title):
    import json as _j
    try:
        return _j.load(open(_links_path(cfg))).get(title)
    except Exception:
        return None


def _link_put(cfg, title, url):
    import json as _j
    try:
        p = _links_path(cfg)
        d = _j.load(open(p)) if os.path.exists(p) else {}
        d[title] = url
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _j.dump(d, open(p, 'w'))
    except Exception:
        pass


def _log_show(cfg, meta, title):
    """Resolve + log ONE page link (Simkl preferred, else MAL); cached."""
    mal = meta.cached_mal(title)
    if mal is None:
        try:
            mal = meta.resolve_mal(title, ask=False)
        except Exception:
            mal = None
    link = _link_get(cfg, title)
    if link is None and mal:
        try:
            link = meta.simkl.show_link(mal=mal)
        except Exception:
            link = None
        if link:
            _link_put(cfg, title, link)
    if link:
        log.cprint(f'show: {link}')
    elif mal:
        log.cprint(f'show: https://myanimelist.net/anime/{mal}')
    else:
        log.cprint('show: not found (no MAL / Simkl match)')


def cache_command(args: List[str]) -> int:
    """`agp cache` (report) / `agp cache clean [--days N|--all]`."""
    cfg = Config()
    c = Cache(cfg.cache_dir, cfg.cache_budget)
    if args and args[0] == 'clean':
        days = 3.0
        if '--days' in args:
            try:
                days = float(args[args.index('--days') + 1])
            except Exception:
                pass
        n = c.clean(days=days, all='--all' in args,
                    include_partials='--keep-partial' not in args)
        print(f'cache: removed {n} file(s) from {cfg.cache_dir}')
        return 0
    rows = c.report()
    total = sum(r['bytes'] for r in rows)
    print(f'cache: {cfg.cache_dir}  ({total // 1048576}MB, {len(rows)} entries)')
    for r in rows:
        tag = 'partial' if r['partial'] else 'done'
        print(f"  {r['bytes'] // 1048576:>6}MB  {r['age_days']:>5.1f}d  "
              f"{tag:<7} {r['name'][:70]}")
    print('  keep: unfinished downloads are never auto-deleted')
    print('  clean older than 3 days:  agp cache clean --days 3')
    print('  clean everything:         agp cache clean --all')
    return 0


def parse(argv: List[str]) -> Tuple[dict, List[str], List[str]]:
    opts = {'a': False, 'skip': False, 'skip_toggle': False, 'e': None,
            'f': None, 'cut': None, 'next': False, 'nowait': False,
            'sync': 'auto'}
    pos: List[str] = []
    mpv: List[str] = []
    env = os.environ.get('TG_PLAYER_FLAGS')
    if env:
        mpv += env.split()
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '-a':
            opts['a'] = True
        elif a == '--skip' or a.startswith('--skip='):
            m = a.split('=', 1)[1].lower() if '=' in a else 'all'
            opts['skip'] = m if m in ('all', 'names', 'auto') else 'all'
        elif a == '--skip-toggle':
            opts['skip_toggle'] = True
        elif a == '--nowait':
            opts['nowait'] = True
        elif a == '--next' or a.startswith('--next='):
            v = int(a.split('=', 1)[1]) if '=' in a else 60
            opts['next'] = max(1, min(v, 99)) / 100
        elif a == '-e':
            if i + 1 < len(argv):
                opts['e'] = argv[i + 1]
                i += 1
        elif a in ('-f', '-q'):
            if i + 1 < len(argv):
                opts['f'] = argv[i + 1]
                i += 1
        elif a == '--no-sync':
            opts['sync'] = 'off'
        elif a == '--cut':
            if i + 1 < len(argv):
                opts['cut'] = int(argv[i + 1])
                i += 1
        elif a.startswith('-'):
            if a in ('--start', '--end', '--volume') and i + 1 < len(argv) \
                    and not argv[i + 1].startswith('-'):
                mpv += [a + '=' + argv[i + 1]]
                i += 1
            else:
                mpv.append(a)
        else:
            pos.append(a)
        i += 1
    return opts, pos, mpv


def _plan(s, opts):
    """Decide the episode numbers for a non-menu run (direct CLI play)."""
    eps = s.provider.episodes()
    if opts['a']:
        return epmod.select(eps, all=True)
    if opts['e']:
        return epmod.select(eps, nums=epmod.parse_range(opts['e']))
    if s.resume and s.resume[1]:           # progress: ep + a position
        start = epmod.resume(eps, s.resume[0])
        if start:
            try:
                ans = input(f'resume "{s.title}" ep {s.resume[0]}? [Y/n] ')
            except EOFError:
                ans = 'n'
            if ans.strip().lower() != 'n':
                return start               # Session.play re-applies the pos
    try:
        val = input('eps [a|2-5,9]: ').strip().lower()
    except EOFError:
        val = 'a'
    if val in ('', 'a', 'all'):
        return epmod.select(eps, all=True)
    return epmod.select(eps, nums=epmod.parse_range(val))


def main(argv: Optional[List[str]] = None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ('-h', '--help') for a in argv) or (argv and argv[0] == 'help'):
        print(HELP)
        return 0
    if argv and argv[0].lower() in ('login', 'logout', 'sync', 'new', 'notify',
                                    'tracking', 'status'):
        from .tracking import Tracker
        Tracker(Config().ensure()).cli(argv[0].lower(), argv[1:])
        return 0
    if argv and argv[0].lower() == 'cache':
        return cache_command(argv[1:])
    if argv and argv[0].lower() in ('icon', 'install-desktop'):
        from .icon import install
        paths = install()
        print(f'icon: installed {len(paths)} file(s) under ~/.local/share '
              '- look for "tgplay" in your app launcher')
        return 0
    if argv and argv[0].lower() == 'simkl':
        from .simkl import Simkl, save_client_id
        if len(argv) > 1 and not argv[1].startswith('-'):
            save_client_id(argv[1])
            print('simkl: client id saved')
        else:
            s = Simkl()
            print('simkl: configured' if s.available()
                  else 'simkl: not configured (agp simkl <CLIENT_ID>)')
        return 0

    from . import ui
    gui = _pick_gui()
    force_gui = '--gui' in argv
    force_curses = '--curses' in argv
    argv = [a for a in argv if a not in ('--gui', '--curses')]
    interactive = bool(force_gui)
    if not argv:  # bare `agp`: open a menu when we can
        if ui.available() or gui.available():
            interactive = True
        else:
            print(HELP)
            return 0
    if any(a in ('--menu', '--tui') for a in argv):
        interactive = True
        argv = [a for a in argv if a not in ('--menu', '--tui')]
    use_gui = bool(interactive and (force_gui or
                                    (not force_curses and gui.available())))
    opts, pos, mpv = parse(argv)
    url = next((a for a in pos if 'animegate' in a), pos[0]) if pos else None
    if interactive and url is None:
        if use_gui:
            from .search import search_all
            shp = HttpClient()
            sfn = lambda q: search_all(q, http=shp, sources=('agp',))
            url = gui.choose_url(ui.recent_list(), sfn)
        else:
            url = ui.choose_url()
        if not url:
            return 0
    if url is None:
        print(HELP)
        return 0

    cfg = Config().ensure()
    http = HttpClient()

    planned = None

    from .tracking import Tracker
    tracker = Tracker(cfg, http)          # "new episodes" checks, low priority
    if tracker.enabled():
        threading.Thread(target=lambda: _notify(tracker), daemon=True).start()

    # GUI path: the unified window (one controller for every CLI) builds its
    # own Session in place - no pre-loaded provider/services needed here.
    if interactive and use_gui:
        from .session import SessionLoader
        from .gui_all import UnifiedWindow
        ui.recent_add(url)
        loader = SessionLoader(cfg, http, base_opts=opts, base_mpv=mpv)
        try:
            UnifiedWindow(loader, cfg, initial=('agp', url)).run()
            return 0
        except Exception as ex:
            log.cprint(f'gui: {ex} - using the terminal menu')
        use_gui = False                   # GUI failed -> the curses menu below

    # --- terminal flows: BOTH the curses menu and direct play go through
    # the ONE Session (same setup path as the desktop window) -----------
    from .session import open_session
    ui.recent_add(url)
    if interactive:
        opts, mpv = setup.apply(opts, mpv, setup.load(cfg.ui))
    s = open_session('agp', url, cfg, http, opts, mpv,
                     wait_titles=bool(interactive))

    if interactive:
        res_ep = s.resume[0] if s.resume else None
        chosen = ui.pick_start(s.labels, res_ep)
        if chosen is None:
            s.close()
            print('menu: cancelled')
            return 0
        res = ui.gather(opts, s.provider.groups, mpv, show_eps=False)
        if res is None:
            s.close()
            print('menu: cancelled')
            return 0
        opts, mpv = res
        setup.save(cfg.ui, opts, mpv)          # remember (play re-saves too)
        planned = chosen
    else:
        planned = [e.num for e in _plan(s, opts)]   # Episode objs -> numbers
    if not planned:
        s.close()
        print('nothing to play')
        return 0

    try:
        s.play(planned, opts, mpv)             # resume line printed inside
    finally:
        s.close()                              # stops the per-run proxy
    return 0
