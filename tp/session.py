"""tp.session - a playable "what you're watching" bundle.

A Session owns one provider + the shared services (proxy, cache, skip,
prefetch, player) and knows how to play a chosen episode list. The unified GUI
can load a fresh Session in place when the user searches or pastes a new link,
without restarting the app. This is the OOP seam between "pick a source" and
"the window".
"""
import threading
import time
from typing import Dict, List, Optional

from . import log
from .cache import Cache
from .episodes import Episode
from .player import Player
from .playlist import Playlist
from .prefetch import Prefetcher
from .proxy import RangeProxy
from .skip import SkipService
from .titles import clean_ep_name


class SessionLoader:
    """Builds a Session for (src, target), honoring remembered options.

    The one loader the unified GUI (`gui_all`) uses. Options are merged in
    strict precedence: CLI-provided `base_opts`/`base_mpv` > the setup saved
    for that source (`setup.load(cfg.ui, src)`) > the defaults.
    """

    def __init__(self, cfg, http, base_opts: dict = None,
                 base_mpv: List[str] = None, wait_titles: bool = True):
        self.cfg = cfg
        self.http = http
        self.base_opts = dict(base_opts or {})
        self.base_mpv = list(base_mpv or [])
        # the window draws labels right away: a brief wait (<=5 s) on the
        # FIRST open means real names now instead of placeholders next time
        self.wait_titles = wait_titles

    def opts_for(self, src: str):
        """(opts, mpv) for a source: base + remembered setup for `src`."""
        o = {'a': False, 'skip': False, 'skip_toggle': False, 'e': None,
             'f': None, 'cut': None, 'next': False, 'nowait': False}
        o.update(self.base_opts)
        from . import setup
        return setup.apply(o, list(self.base_mpv), setup.load(self.cfg.ui, src))

    def __call__(self, src, target):
        o, m = self.opts_for(str(src or 'agp'))
        return open_session(str(src or 'agp'), target, self.cfg, self.http,
                            o, m, wait_titles=self.wait_titles)


def make_loader(cfg, http) -> SessionLoader:
    """A `loader(src, target) -> Session`, shared by `tgplay`, `agp`, `axp`."""
    return SessionLoader(cfg, http)


def _resume(cfg, title):
    import json as _j
    try:
        e = _j.load(open(cfg.progress)).get(title, {})
        return (int(e.get('ep')), int(e.get('pos') or 0)) if e.get('ep') else None
    except Exception:
        return None


class Session:
    """One provider, ready to show and play. Build via `open_session`."""

    def __init__(self, src: str, provider, cfg, http, meta, titles, *,
                 groups: List[dict], labels: Dict[int, str],
                 resume: Optional[tuple], opts: dict, mpv: List[str],
                 audio: bool = False, link: Optional[str] = None,
                 mal_id=None):
        self.src = src
        self.provider = provider
        self.mal_id = mal_id      # pinned MAL entry (cast + sync key)
        self.cfg = cfg
        self.http = http
        self.meta = meta
        self.titles = titles
        self.groups = groups
        self.labels = labels
        self.resume = resume                # (episode, position) or None
        self.opts = dict(opts)
        self.mpv = list(mpv)
        self.audio = audio
        self.link = link
        self.title = provider.title
        self._proxy: Optional[RangeProxy] = None
        self._player = Player(referer=('https://megaplay.buzz/' if src == 'axp'
                                       else 'https://animegate.ir/'))
        self._skip = SkipService(metadata=meta)
        self._cache = Cache(cfg.cache_dir, cfg.cache_budget)
        self._prefetch = Prefetcher(self._cache)

    # --- playback -------------------------------------------------------
    def play(self, chosen: List[int], o: dict, m: List[str]):
        # remember this run's setup for the next launch (per source);
        # the GUI changes opts per play, so the state lives in the Session
        try:
            from . import setup
            setup.save(self.cfg.ui, o, m, self.src)
        except Exception:
            pass
        self._player.stop()
        # the Telegram views are already narrowed/planned at build time:
        # re-selecting here would renumber them (see cli_telegram)
        if self.src == 'axp':                  # audio first: select() keeps it
            self.provider.set_audio(o.get('audio') or 'dub')
        if self.src not in ('tg', 'tgp'):
            self.provider.select(o.get('f'))
        eps = self.provider.episodes()
        planned = [Episode(k, eps[k]) for k in chosen if k in eps]
        if not planned:
            return
        if self._proxy is None:
            self._proxy = RangeProxy(port=self.cfg.proxy_port).start()
        try:
            from .tracking import make_tracker
            tracker = make_tracker(self.cfg, self.http,
                                   sync=(o.get('sync', 'auto') != 'off'))
        except Exception:
            tracker = None
        playlist = Playlist(self.provider, self._proxy, self._cache,
                            self._player, self.cfg, skip=self._skip,
                            prefetcher=self._prefetch, tracker=tracker,
                            mal_id=self.mal_id)
        start = self.resume[1] if (self.resume and planned[0].num == self.resume[0]) else None
        if start:
            _m, _s = divmod(int(start), 60)
            log.cprint(f'resume: ep{planned[0].num} at {_m:d}:{_s:02d} '
                       f'(mpv --start={int(start)})')
        nf = ('cut' if (o.get('nowait') and o.get('cut')) else o.get('next')) \
            if o.get('next') else False
        sm = o.get('skip')
        skip_mode = sm if (isinstance(sm, str) and
                           sm in ('all', 'names', 'auto', 'off')) else 'all'
        playlist.run(planned, skip_mode=skip_mode,
                     skip_toggle=bool(o.get('skip_toggle')), cut=o.get('cut'),
                     start=start, next_frac=nf, extra=m)

    def refresh_labels(self) -> 'Session':
        """Re-pull the episode labels after the provider view changed."""
        self.labels = dict(self.provider.episodes())
        return self

    def stop(self):
        self._player.stop()

    def close(self):
        if self._proxy is not None:
            try:
                self._proxy.stop()
            except Exception:
                pass
            self._proxy = None

    def status(self) -> str:
        import json as _j
        try:
            e = _j.load(open(self.cfg.progress)).get(self.title, {})
        except Exception:
            e = {}
        ep, pos = e.get('ep'), int(e.get('pos') or 0)
        if not ep:
            return 'idle'
        mm, ss = divmod(pos, 60)
        return f'ep {ep}   {mm:02d}:{ss:02d}'


def _safe_mal(meta, title):
    """Fuzzy title -> MAL id (never raises); the found id is pinned to the
    link by the caller. Whether its names may be PAINTED onto a page is
    decided by the paint guard in TitleService.labels()."""
    try:
        mal = meta.cached_mal(title)
        if mal is None:
            mal = meta.resolve_mal(title, ask=False)
        return mal
    except Exception:
        return None


def _telegram_target(target):
    """('channel', msg_id) for a t.me link / 'channel msgid' (msg_id may be None)."""
    import re
    m = re.search(r't\.me/([A-Za-z0-9_]+)(?:/(\d+))?', target or '')
    if m:
        return m.group(1), (int(m.group(2)) if m.group(2) else None)
    parts = (target or '').split()
    if len(parts) >= 2 and parts[1].isdigit():
        return parts[0].lstrip('@'), int(parts[1])
    return (target or '').lstrip('@'), None


def open_session(src: str, target: str, cfg, http, opts: dict = None,
                 mpv: List[str] = None, *, wait_titles: bool = False,
                 window: int = None, matcher: str = None) -> Session:
    """Build a Session for (src, target): agp / axp / tgp / tg.

    - `wait_titles`: block briefly (≤5 s) on missing episode names — the
      curses menu wants them now instead of next launch.
    - `window`/`matcher`: Telegram-only knobs (--window N, -f name matcher).
    """
    from .cli import _link_get, _log_show
    from .metadata import Metadata
    from .titles import TitleService

    opts = dict(opts or {})
    mpv = list(mpv or [])
    t_open = time.monotonic()
    meta = Metadata(cfg, http)
    titles = TitleService(meta, cfg)
    src = (src or 'agp').lower()
    mal = None                                    # pinned MAL entry (per src)

    if src == 'axp':
        from .providers.animex import AnimeXProvider
        prov = AnimeXProvider(target, quality=opts.get('f'),
                              audio=opts.get('audio') or 'dub', http=http)
        prov.set_audio(opts.get('audio') or 'dub')
        prov.fetch_groups()
        prov.select(opts.get('f'))
        groups = prov.groups
        # the AnimeX API embeds Bangumi's 'Release: date - ' marker in the
        # titles of (already-aired) episodes — clean BEFORE anything reads
        labels = {n: (clean_ep_name(t) or t)
                  for n, t in dict(prov.episodes()).items()}
        audio = True
        # SAME name sync as AGP: the AnimeX API usually only serves generic
        # 'Episode N' - fill real names from the MAL/Simkl episode cache.
        # The provider carries the EXACT MAL id of the entry (AnimeX gives
        # us malId); the id is pinned to the link so it never re-resolves.
        mal = getattr(prov, 'mal_id', None) or meta.link_mal(str(target)) \
            or _safe_mal(meta, prov.title)
        if mal:
            labels = titles.labels(mal, labels)
            meta.remember_link_mal(str(target), mal)
            missing_now = [n for n in labels
                           if str(labels[n]).startswith('Episode ')]
            if missing_now and len(missing_now) == len(labels):
                cached = titles.cache_count(mal)
                if cached and cached != len(labels):
                    log.cprint(f'titles: kept clean - MAL lists {cached} '
                               f'episodes but this page has {len(labels)}; '
                               'painting would mix seasons')
        missing = [n for n in labels if str(labels[n]).startswith('Episode ')]
        if missing and mal:
            log.cprint(f'titles: looking up {len(missing)} missing '
                       'episode name(s)...')
            ax_th = threading.Thread(
                target=lambda: meta.refresh_titles(mal, prov.title),
                daemon=True)
            ax_th.start()
            if wait_titles:              # the curses menu wants names NOW
                ax_th.join(timeout=5)
                if ax_th.is_alive():
                    log.cprint('titles: still fetching names in the '
                               'background (they will show next time)')
            labels = titles.labels(mal, labels)      # re-read post-join
            meta._refreshed.add(mal)
    elif src in ('tg', 'tgp'):
        from .providers.telegram import SingleFileProvider, TelegramProvider
        chat, msg_id = _telegram_target(target)
        if src == 'tg' and msg_id is not None:
            prov = SingleFileProvider(chat, msg_id, cfg.tg_session)
            prov.load()
            labels = dict(prov.episodes())
        else:
            prov = TelegramProvider(chat, session=cfg.tg_session,
                                    window=int(window or 50),
                                    matcher=matcher)
            prov.load()
            labels = dict(prov.episodes())
        groups = []
        audio = False
    else:                                    # agp (default)
        from .providers.animegate import AnimeGateProvider
        prov = AnimeGateProvider(target, quality=opts.get('f'), http=http)
        prov.fetch_groups()
        prov.select(opts.get('f'))
        eps = prov.episodes()
        # MAL id: pinned link id first, else fuzzy title resolution — find
        # it once and it sticks to this page forever
        mal = meta.link_mal(str(target)) or _safe_mal(meta, prov.title)
        labels = titles.labels(mal, {n: f'Episode {n}' for n in eps})
        missing = [n for n in labels
                   if str(labels[n]).startswith('Episode ')]
        if mal and missing and len(missing) == len(labels):
            cached = titles.cache_count(mal)
            if cached and cached != len(eps):
                log.cprint(f'titles: kept clean - MAL lists {cached} '
                           f'episodes but this page has {len(eps)}; painting '
                           'would mix seasons (pick the per-season link to '
                           'get the right names)')
        th = None
        if missing and mal:
            log.cprint(f'titles: looking up {len(missing)} missing '
                       'episode name(s)...')
            th = threading.Thread(
                target=lambda: meta.refresh_titles(mal, prov.title),
                daemon=True)
            th.start()
            if wait_titles:                  # the terminal menu wants names NOW
                th.join(timeout=5)
                if th.is_alive():
                    log.cprint('titles: still fetching names in the '
                               'background (they will show next time)')
            labels = titles.labels(mal, {n: f'Episode {n}' for n in eps})
            meta._refreshed.add(mal)
        if mal:
            meta.remember_link_mal(str(target), mal)
        groups = prov.groups
        audio = False

    log.cprint(f'>> {prov.title} - {len(labels)} episodes '
               f'({time.monotonic() - t_open:.1f}s)')

    link = _link_get(cfg, prov.title)
    if link is None and src != 'tg':
        try:
            _log_show(cfg, meta, prov.title)
        except Exception:
            pass
        link = _link_get(cfg, prov.title)

    return Session(src, prov, cfg, http, meta, titles, groups=groups,
                   labels=labels, resume=_resume(cfg, prov.title), opts=opts,
                   mpv=mpv, audio=audio, link=link, mal_id=mal)
