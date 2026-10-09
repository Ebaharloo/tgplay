"""tp.cli_telegram - the `tg` (one file) and `tgp` (channel playlist) CLIs.

Both reuse the exact same Player/Playlist/RangeProxy as `agp`; only the
Provider differs. `--menu` opens the same curses form (no Quality row, since
Telegram files have no quality groups).
"""
import json
import re
import sys
from typing import List, Optional

from .cache import Cache
from .config import Config
from .episodes import Episode, parse_range, select
from .metadata import Metadata
from .player import Player
from .playlist import Playlist
from .prefetch import Prefetcher
from .providers.telegram import SingleFileProvider, TelegramProvider
from .proxy import RangeProxy
from .skip import SkipService
from .cli import parse
from . import setup

TG_HELP = """\
tg (tgplay) - stream one Telegram video via a local range proxy.

  tg <t.me link>            e.g. tg "https://t.me/SomeChannel/2598"
  tg <channel> <msg_id>
  tg --menu [<link>]        pick options (and the link) in the terminal form
  tg login | tg logout      one-time login / forget the session
  [opts]                    --skip[=MODE]  --skip-toggle  --cut N  --start N

  login is single-shot: it does NOT retry. Do not attempt it repeatedly -
  Telegram rate-limits (FloodWait) and can temporarily block the account.
"""

TGP_HELP = """\
tgp (tgplay) - stream the last 50 mkv files of a Telegram channel.

  tgp --menu [<channel>]    pick quality, options and the START episode
  tgp <channel> -e 2-5,9    play picks directly (no menu)
  tgp <channel> -a          play all 50
  tgp <channel> -f 720      filter by name substring
  tgp <channel> --window N  scan N newest files (default 50)
  tgp cache [clean --days 3]   show / clean the download cache
  tgp login | tgp logout    one-time login / forget the session

  Quality is read from the file names (480p/720p/1080p/4K); unfinished
  downloads are kept for later - `tgp cache` reports them.

  login is single-shot: it does NOT retry. Do not attempt it repeatedly -
  Telegram rate-limits (FloodWait) and can temporarily block the account.
"""


def _strip_menu(argv):
    interactive = any(a in ('--menu', '--tui') for a in argv)
    return [a for a in argv if a not in ('--menu', '--tui')], interactive


def _run(provider, episodes, opts, mpv):
    cfg = Config().ensure()
    proxy = RangeProxy(port=cfg.proxy_port).start()
    cache = Cache(cfg.cache_dir, cfg.cache_budget)
    skip = SkipService(metadata=Metadata(cfg))
    playlist = Playlist(provider, proxy, cache, Player(referer='https://t.me/'),
                        cfg, skip=skip, prefetcher=Prefetcher(cache))
    next_frac = False
    if opts['next']:
        next_frac = 'cut' if (opts['nowait'] and opts['cut']) else opts['next']
    try:
        playlist.run(episodes, skip_mode=(opts['skip'] or 'all'),
                     skip_toggle=opts['skip_toggle'], cut=opts['cut'],
                     next_frac=next_frac, extra=mpv)
    finally:
        proxy.stop()


def _maybe_login(argv) -> bool:
    if argv and argv[0] in ('login', 'tg-login'):
        from .providers.telegram import login
        me = login(Config().tg_session)
        if me is not None:
            print('logged in as', getattr(me, 'first_name', me))
        return True
    if argv and argv[0] in ('logout', 'tg-logout'):
        from .providers.telegram import logout
        print('telegram: logged out' if logout(Config().tg_session)
              else 'telegram: no session to remove')
        return True
    if argv and argv[0] == 'cache':
        from .cli import cache_command
        cache_command(argv[1:])
        return True
    return False


def _resume_ep(cfg, title) -> Optional[int]:
    try:
        d = json.load(open(cfg.progress))
        e = d.get(title, {})
        return int(e.get('ep')) if e.get('ep') else None
    except Exception:
        return None


def _chat_msg(pos):
    if not pos:
        return None, None
    m = re.search(r't\.me/([A-Za-z0-9_]+)/(\d+)', pos[0])
    if m:
        return m.group(1), int(m.group(2))
    if len(pos) >= 2 and str(pos[1]).isdigit():
        return pos[0], int(pos[1])
    return None, None


def main_tg(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ('-h', '--help') for a in argv):
        print(TG_HELP)
        return 0
    if _maybe_login(argv):
        return 0
    from . import ui
    argv, interactive = _strip_menu(argv)
    opts, pos, mpv = parse(argv)
    chat, msg_id = _chat_msg(pos)
    if chat is None and interactive and ui.available():
        link = ui.prompt('Telegram t.me link')
        m = re.search(r't\.me/([A-Za-z0-9_]+)/(\d+)', link or '')
        if m:
            chat, msg_id = m.group(1), int(m.group(2))
    if chat is None:
        print(TG_HELP)
        return 0
    provider = SingleFileProvider(chat, msg_id, Config().tg_session)
    provider.load()
    if interactive:
        res = ui.gather(opts, [], mpv)
        if res is None:
            print('menu: cancelled')
            return 0
        opts, mpv = res
    _run(provider, [Episode(1, f'{chat}/{msg_id}')], opts, mpv)
    return 0


def main_tgp(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ('-h', '--help') for a in argv):
        print(TGP_HELP)
        return 0
    if _maybe_login(argv):
        return 0
    from . import ui
    window = 50
    if '--window' in argv:
        i = argv.index('--window')
        if i + 1 < len(argv):
            try:
                window = int(argv[i + 1])
            except ValueError:
                pass
            del argv[i:i + 2]
        else:
            del argv[i]
    if '--all' in argv:
        window = 500
        argv.remove('--all')
    interactive = not argv
    argv, menu = _strip_menu(argv)
    interactive = interactive or menu
    opts, pos, mpv = parse(argv)
    channel = pos[0] if pos else None
    if channel is None:
        if interactive and ui.available():
            channel = ui.prompt('Telegram channel')
        if not channel:
            print(TGP_HELP)
            return 0
        interactive = True
    provider = TelegramProvider(channel, session=Config().tg_session,
                                window=window, matcher=opts['f'])
    provider.load()
    cfg = Config()
    qs = provider.qualities()
    quality_groups = [{'label': q} for q in qs]
    if interactive:
        opts, mpv = setup.apply(opts, mpv, setup.load(cfg.ui, 'tgp'))
        res = ui.gather(opts, quality_groups, mpv, show_eps=False)
        if res is None:
            print('menu: cancelled')
            return 0
        opts, mpv = res
        setup.save(cfg.ui, opts, mpv, 'tgp')  # remember for next time
        if qs:
            provider.set_quality(opts.get('f'))
        eps = provider.episodes()
        chosen = ui.pick_start(eps, _resume_ep(cfg, channel))
        if chosen is None:
            print('menu: cancelled')
            return 0
        planned = [Episode(k, eps[k]) for k in chosen]
    else:
        if qs and opts.get('f') in qs:
            provider.set_quality(opts['f'])
        eps = provider.episodes()
        direct = next((a for a in pos if a != channel), None) or opts['e']
        if opts['a'] or direct == 'a':
            planned = select(eps, all=True)
        elif direct:
            planned = select(eps, nums=parse_range(direct))
        else:
            print(f'\n[ last {len(eps)} mkv | {eps[1]} ... {eps[len(eps)]} ]')
            for k in sorted(eps):
                print(f'{k}) {eps[k]}')
            try:
                val = input('\npick [1|2-5,9|a|q]: ').strip().lower()
            except EOFError:
                val = 'q'
            if val in ('', 'q'):
                return 0
            planned = select(eps, all=True) if val == 'a' \
                else select(eps, nums=parse_range(val))
    if not planned:
        print('nothing to play')
        return 0
    _run(provider, planned, opts, mpv)
    return 0
