"""tp.cli_animex - the `axp` CLI: animex.one with English sub/dub servers.

Same Player / Playlist / proxy / menu / skip as `agp`; only the Provider and
one extra idea differ: AnimeX streams HLS, so playback hands the remote m3u8
to mpv directly (see tp.sources.DirectSource) instead of through the range
proxy. Every audio x server AnimeX reports is offered in the menu; dub is the
default. Electronically nothing else is special-cased.
"""
import sys
from typing import List, Optional

from .cache import Cache
from .config import Config
from .episodes import Episode
from .http import HttpClient
from .metadata import Metadata
from .player import Player
from .playlist import Playlist
from .prefetch import Prefetcher
from .providers.animex import AnimeXProvider
from .proxy import RangeProxy
from .skip import SkipService
from .cli import parse, _resume_ep, _resume_pos, _link_get, _log_show, _plan
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
    meta = Metadata(cfg, http)
    try:
        provider = AnimeXProvider(url, quality=opts['f'], audio=audio, http=http)
    except ValueError as ex:
        print(f'axp: {ex}')
        return 2

    resume_pt = None
    labels = None
    res_ep = None
    chosen = None

    if interactive:
        opts, mpv = setup.apply(opts, mpv, setup.load(cfg.ui, 'axp'))
        provider.set_audio(opts.get('audio') or audio)
        provider.fetch_groups()
        provider.select(opts['f'])
    else:
        provider.load()
    try:
        ui.recent_add(url)
    except Exception:
        pass
    log.cprint(f'>> {provider.title} - {len(provider.episodes())} episodes')
    _log_show(cfg, meta, provider.title)   # MAL/Simkl link before the menu

    planned = None
    if interactive:
        eps = provider.episodes()
        labels = dict(eps)                  # AnimeX gives real titles
        res_ep = _resume_ep(cfg, provider.title)
        resume_pt = (res_ep, _resume_pos(cfg, provider.title))
        if not use_gui:
            chosen = ui.pick_start(labels, res_ep)
            if chosen is None:
                print('menu: cancelled')
                return 0
            res = ui.gather(opts, provider.groups, mpv, show_eps=False,
                            audio=True)
            if res is None:
                print('menu: cancelled')
                return 0
            opts, mpv = res
            setup.save(cfg.ui, opts, mpv, 'axp')
            provider.set_audio(opts.get('audio') or audio)
            provider.select(opts['f'])
            eps = provider.episodes()
            planned = [Episode(k, eps[k]) for k in chosen if k in eps]

    proxy = RangeProxy(port=cfg.proxy_port).start()
    cache = Cache(cfg.cache_dir, cfg.cache_budget)
    skip = SkipService(metadata=meta)
    prefetch = Prefetcher(cache)
    player = Player(referer='https://animex.one/')
    from .tracking import make_tracker
    play_tracker = make_tracker(cfg, http,
                                sync=(opts.get('sync', 'auto') != 'off'))
    playlist = Playlist(provider, proxy, cache, player, cfg,
                        skip=skip, prefetcher=prefetch, tracker=play_tracker)

    if use_gui and interactive:
        def _play(c, o, m):
            player.stop()
            provider.set_audio(o.get('audio') or audio)
            provider.select(o['f'])
            e2 = provider.episodes()
            pl = [Episode(k, e2[k]) for k in c if k in e2]
            if not pl:
                return
            st = resume_pt[1] if (resume_pt and pl[0].num == resume_pt[0]) else None
            nf = ('cut' if (o['nowait'] and o['cut']) else o['next']) \
                if o['next'] else False
            setup.save(cfg.ui, o, m, 'axp')
            playlist.run(pl, skip_mode=(o['skip'] or 'all'),
                         skip_toggle=o['skip_toggle'], cut=o['cut'],
                         start=st, next_frac=nf, extra=m)

        def _status():
            import json as _j
            try:
                e = _j.load(open(cfg.progress)).get(provider.title, {})
            except Exception:
                e = {}
            ep, pos = e.get('ep'), int(e.get('pos') or 0)
            if not ep:
                return 'idle'
            mm, ss = divmod(pos, 60)
            return f'ep {ep}   {mm:02d}:{ss:02d}'

        try:
            gui.controller(provider.title, _link_get(cfg, provider.title),
                           provider.groups, labels, res_ep, opts, mpv,
                           _play, stop_fn=player.stop, status_fn=_status,
                           audio=True)
        except Exception as ex:
            log.cprint(f'gui: {ex} - using the terminal menu')
        else:
            proxy.stop()
            return 0
        chosen = ui.pick_start(labels, res_ep)
        if chosen is None:
            proxy.stop()
            print('menu: cancelled')
            return 0
        res = ui.gather(opts, provider.groups, mpv, show_eps=False, audio=True)
        if res is None:
            proxy.stop()
            print('menu: cancelled')
            return 0
        opts, mpv = res
        provider.set_audio(opts.get('audio') or audio)
        provider.select(opts['f'])
        eps = provider.episodes()
        planned = [Episode(k, eps[k]) for k in chosen if k in eps]

    if not interactive:
        planned = _plan(provider, opts, playlist)
    if not planned:
        proxy.stop()
        print('nothing to play')
        return 0

    next_frac = False
    if opts['next']:
        next_frac = 'cut' if (opts['nowait'] and opts['cut']) else opts['next']
    start = None
    rp = getattr(playlist, '_resume', None) or resume_pt
    if rp and planned and planned[0].num == rp[0]:
        start = rp[1]
    if start:
        _m, _s = divmod(int(start), 60)
        log.cprint(f'resume: ep{planned[0].num} at {_m:d}:{_s:02d} '
                   f'(mpv --start={int(start)})')
    try:
        playlist.run(planned, skip_mode=(opts['skip'] or 'all'),
                     skip_toggle=opts['skip_toggle'], cut=opts['cut'],
                     start=start, next_frac=next_frac, extra=mpv)
    finally:
        proxy.stop()
    return 0
