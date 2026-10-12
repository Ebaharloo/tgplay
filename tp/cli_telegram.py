"""tp.cli_telegram - the `tg` (one file) and `tgp` (channel playlist) CLIs.

Both reuse the exact same Player/Playlist/RangeProxy as `agp`; only the
Provider differs. `--menu` opens the same curses form (no Quality row, since
Telegram files have no quality groups).
"""
import re
import sys
from typing import List, Optional

from .config import Config
from .episodes import parse_range, select
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
    from .session import open_session
    s = open_session('tg', f'{chat} {msg_id}', Config().ensure(),
                     None, opts, mpv)
    try:
        if interactive:
            res = ui.gather(opts, [], mpv)      # same curses form (no quality)
            if res is None:
                print('menu: cancelled')
                return 0
            opts, mpv = res
        s.play([1], opts, mpv)                  # one file = one episode
    finally:
        s.close()
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
    cfg = Config().ensure()
    from .session import open_session
    s = open_session('tgp', channel, cfg, None, opts, mpv,
                     window=window, matcher=opts['f'])
    try:
        if interactive:
            opts, mpv = setup.apply(opts, mpv, setup.load(cfg.ui, 'tgp'))
            res = ui.gather(opts, [{'label': q} for q in s.provider.qualities()],
                            mpv, show_eps=False)
            if res is None:
                print('menu: cancelled')
                return 0
            opts, mpv = res
            setup.save(cfg.ui, opts, mpv, 'tgp')   # remember for next time
            if s.provider.qualities():
                s.provider.set_quality(opts.get('f'))
            s.refresh_labels()
            chosen = ui.pick_start(s.labels,
                                   s.resume[0] if s.resume else None)
            if chosen is None:
                print('menu: cancelled')
                return 0
            planned = chosen
        else:
            if s.provider.qualities() and opts.get('f') in \
                    s.provider.qualities():
                s.provider.set_quality(opts['f'])
            s.refresh_labels()
            eps = s.provider.episodes()
            direct = next((a for a in pos if a != channel), None) or opts['e']
            if opts['a'] or direct == 'a':
                planned = sorted(eps)
            elif direct:
                planned = [e.num for e in select(eps, nums=parse_range(direct))]
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
                planned = sorted(eps) if val == 'a' \
                    else [e.num for e in select(eps, nums=parse_range(val))]
        if not planned:
            print('nothing to play')
            return 0
        s.play(planned, opts, mpv)
    finally:
        s.close()
    return 0
