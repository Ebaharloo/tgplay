"""tp.cli_animex - the `axp` CLI: animex.one with English sub/dub servers.

Same Player / Playlist / proxy / menu / skip as `agp`; only the Provider and
one extra idea differ: AnimeX streams HLS, so playback hands the remote m3u8
to mpv directly (see tp.sources.DirectSource) instead of through the range
proxy. Every audio x server AnimeX reports is offered in the menu; dub is the
default. Electronically nothing else is special-cased.
"""
import sys
from typing import List, Optional

from .config import Config
from .http import HttpClient
from .providers.animex import AnimeXProvider
from .cli import parse, _plan
from . import setup
from . import log

AXP_HELP = """\
axp (tgplay) - stream animex.one with English sub/dub, via mpv.

  axp <animex-url>          e.g. axp https://animex.one/anime/<slug>
  axp --menu [<url>]        pick audio/server, options and START episode
  axp                       (a display) opens the app window with a link picker
  -e RANGE / -a             episode selection (no menu)
  --dub / --sub / --auto    audio (default: dub; auto = dub if available,
                            else sub). The menu has an Audio row too.
  --skip[=MODE] --skip-toggle --cut N --start N --next[=P] [mpv flags]
  --gui / --curses          force the desktop window / the terminal menu

  Servers are whatever AnimeX reports (sub + dub); if one fails, the next is
  tried automatically. HLS is played by mpv directly (no local download cache).
"""


def _pick_gui():
    try:
        from . import gui_qt
        if gui_qt.available():
            return gui_qt
    except Exception:
        pass
    from . import gui
    return gui


def main_axp(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ('-h', '--help') for a in argv):
        print(AXP_HELP)
        return 0

    from . import ui
    force_gui = '--gui' in argv
    force_curses = '--curses' in argv
    argv = [a for a in argv if a not in ('--gui', '--curses')]
    audio = 'sub' if '--sub' in argv else ('auto' if '--auto' in argv else 'dub')
    argv = [a for a in argv if a not in ('--sub', '--dub', '--auto')]

    interactive = bool(force_gui)
    gui = _pick_gui()
    if not argv:
        if ui.available() or gui.available():
            interactive = True
        else:
            print(AXP_HELP)
            return 0
    if any(a in ('--menu', '--tui') for a in argv):
        interactive = True
        argv = [a for a in argv if a not in ('--menu', '--tui')]
    use_gui = bool(interactive and (force_gui or
                                    (not force_curses and gui.available())))

    opts, pos, mpv = parse(argv)
    opts['audio'] = audio
    url = next((a for a in pos if 'animex' in a), pos[0]) if pos else None
    if interactive and url is None:
        if use_gui:
            from .search import search_all
            shp = HttpClient()
            sfn = lambda q: search_all(q, http=shp, sources=('axp',))
            url = gui.choose_url(ui.recent_list(), sfn)
        else:
            url = ui.choose_url()
        if not url:
            return 0
    if url is None:
        print(AXP_HELP)
        return 0

    cfg = Config().ensure()
    http = HttpClient()
    try:
        AnimeXProvider(url, quality=opts['f'], audio=audio, http=http)
    except ValueError as ex:               # early, clean bad-slug/quality UX
        print(f'axp: {ex}')
        return 2

    # GUI path first: the unified window builds its own Session in place
    # (fetches groups/episodes itself), so nothing else is pre-loaded here.
    if interactive and use_gui:
        from .session import SessionLoader
        from .gui_all import UnifiedWindow
        try:
            ui.recent_add(url)            # same recent list the dialog shows
        except Exception:
            pass
        loader = SessionLoader(cfg, http, base_opts=opts, base_mpv=mpv)
        try:
            UnifiedWindow(loader, cfg, initial=('axp', url)).run()
            return 0
        except Exception as ex:
            log.cprint(f'gui: {ex} - using the terminal menu')
        use_gui = False                   # GUI failed -> the curses menu below

    # --- terminal flows: both the curses menu and direct play go through
    # the ONE Session (same setup path as the desktop window) -----------
    from .session import open_session
    if interactive:
        opts, mpv = setup.apply(opts, mpv, setup.load(cfg.ui, 'axp'))
    s = open_session('axp', url, cfg, http, opts, mpv)

    if interactive:
        res_ep = s.resume[0] if s.resume else None
        chosen = ui.pick_start(s.labels, res_ep)
        if chosen is None:
            s.close()
            print('menu: cancelled')
            return 0
        res = ui.gather(opts, s.provider.groups, mpv, show_eps=False,
                        audio=True)
        if res is None:
            s.close()
            print('menu: cancelled')
            return 0
        opts, mpv = res
        setup.save(cfg.ui, opts, mpv, 'axp')   # remember (play re-saves too)
        planned = chosen
    else:
        planned = [e.num for e in _plan(s, opts)]   # Episode objs -> numbers
    if not planned:
        s.close()
        print('nothing to play')
        return 0

    try:
        s.play(planned, opts, mpv)
    finally:
        s.close()
    return 0
