"""tp.cli - argument parsing and wiring; the `agp` entry point.

`parse()` builds the same flag set the original `opts.py` did; `main()` wires
the services together and runs the Playlist. No globals.
"""
import os
import sys
import threading
from typing import List, Optional, Tuple

from .cache import Cache
from .config import Config
from .http import HttpClient
from .player import Player
from .playlist import Playlist
from .prefetch import Prefetcher
from .proxy import RangeProxy
from .skip import SkipService
from .metadata import Metadata
from .providers.animegate import AnimeGateProvider
from . import episodes as epmod
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
  any other --flag goes to mpv verbatim

  agp --menu                pick the link + options in a terminal form
  agp cache [clean [--days N]]  show / clean the download cache
  agp login <CLIENT_ID> | logout | sync [--dry] | new | tracking
                            AniList progress sync + new-episode notices
  Telegram: use ./tg (one file) and ./tgp (channel); log in with `tgp login`.
"""


def _notify(tracker):
    try:
        tracker.notify_new()
    except Exception:
        pass


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
            'f': None, 'cut': None, 'next': False, 'nowait': False}
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


def _plan(provider, opts, playlist):
    eps = provider.episodes()
    if opts['a']:
        return epmod.select(eps, all=True)
    if opts['e']:
        return epmod.select(eps, nums=epmod.parse_range(opts['e']))
    prog = playlist.progress_for(provider.title)
    if prog and prog.get('pos') and prog.get('ep'):
        start = epmod.resume(eps, prog['ep'])
        if start:
            try:
                ans = input(f'resume "{provider.title}" ep {prog["ep"]}? [Y/n] ')
            except EOFError:
                ans = 'n'
            if ans.strip().lower() != 'n':
                playlist._resume = (prog['ep'], int(prog['pos']))
                return start
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

    from . import ui
    interactive = False
    if not argv:  # bare `agp`: open the menu when we have a terminal
        if ui.available():
            interactive = True
        else:
            print(HELP)
            return 0
    if any(a in ('--menu', '--tui') for a in argv):
        interactive = True
        argv = [a for a in argv if a not in ('--menu', '--tui')]
    opts, pos, mpv = parse(argv)
    url = next((a for a in pos if 'animegate' in a), pos[0]) if pos else None
    if interactive and url is None:
        url = ui.choose_url()
        if not url:
            return 0
    if url is None:
        print(HELP)
        return 0

    cfg = Config().ensure()
    http = HttpClient()
    provider = AnimeGateProvider(url, quality=opts['f'], http=http)
    if interactive:
        provider.fetch_groups()
        res = ui.gather(opts, provider.groups, mpv)
        if res is None:
            print('menu: cancelled')
            return 0
        opts, mpv = res
        provider.select(opts['f'])
    else:
        provider.load()
    ui.recent_add(url)
    log.cprint(f'>> {provider.title} - {len(provider.episodes())} episodes')

    from .tracking import Tracker
    tracker = Tracker(cfg, http)
    if tracker.enabled():
        threading.Thread(target=lambda: _notify(tracker), daemon=True).start()

    proxy = RangeProxy(port=cfg.proxy_port).start()
    cache = Cache(cfg.cache_dir, cfg.cache_budget)
    meta = Metadata(cfg, http)
    skip = SkipService(metadata=meta)
    prefetch = Prefetcher(cache)
    player = Player()
    playlist = Playlist(provider, proxy, cache, player, cfg,
                        skip=skip, prefetcher=prefetch, tracker=tracker)

    planned = _plan(provider, opts, playlist)
    if not planned:
        print('nothing to play')
        return 0

    next_frac = False
    if opts['next']:
        next_frac = 'cut' if (opts['nowait'] and opts['cut']) else opts['next']
    skip_mode = opts['skip'] or 'all'
    start = None
    if getattr(playlist, '_resume', None):
        ep0, pos0 = playlist._resume
        if planned and planned[0].num == ep0:
            start = pos0
    try:
        playlist.run(planned, skip_mode=skip_mode,
                     skip_toggle=opts['skip_toggle'], cut=opts['cut'],
                     start=start, next_frac=next_frac, extra=mpv)
    finally:
        proxy.stop()
    return 0
