"""tp.cli - argument parsing and wiring; the `agp` entry point.

`parse()` builds the same flag set the original `opts.py` did; `main()` wires
the services together and runs the Playlist. No globals.
"""
import os
import sys
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

  NOTE: this is the OOP rewrite (tgplay). The menu, AniList sync and Telegram
  backends land in later phases; see ARCHITECTURE.md.
"""


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
    if not argv or any(a in ('-h', '--help') for a in argv):
        print(HELP)
        return 0
    opts, pos, mpv = parse(argv)
    if not pos:
        print(HELP)
        return 0
    url = next((a for a in pos if 'animegate' in a), pos[0])

    cfg = Config().ensure()
    http = HttpClient()
    provider = AnimeGateProvider(url, quality=opts['f'], http=http)
    provider.load()
    log.cprint(f'>> {provider.title} - {len(provider.episodes())} episodes')

    proxy = RangeProxy(port=cfg.proxy_port).start()
    cache = Cache(cfg.cache_dir, cfg.cache_budget)
    meta = Metadata(cfg, http)
    skip = SkipService(metadata=meta)
    prefetch = Prefetcher(cache)
    player = Player()
    playlist = Playlist(provider, proxy, cache, player, cfg,
                        skip=skip, prefetcher=prefetch)

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
