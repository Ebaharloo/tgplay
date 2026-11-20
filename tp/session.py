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
from .options import PlaybackOptions
from .player import Player
from .playlist import Playlist
from .prefetch import Prefetcher
from .proxy import RangeProxy
from .skip import SkipService


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
        self._stop = threading.Event()   # Stop = stop the WHOLE playlist
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
        # the player's default referer is the source's own auth knowledge
        self._player = Player(referer=self.provider.auth.default_referer())
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
        # audio choice at play time: each source's own Audio object applies
        # it (axp + zoro have one; tg/agp's NoAudio is a no-op)
        self.provider.audio.prepare(self.provider, o.get('audio'))
        if self.provider.servers.reselects:    # tg views must not renumber
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
        self._stop.clear()
        playlist = Playlist(self.provider, self._proxy, self._cache,
                            self._player, self.cfg, skip=self._skip,
                            prefetcher=self._prefetch, tracker=tracker,
                            mal_id=self.mal_id, stop=self._stop)
        po = PlaybackOptions(o, m)
        # an explicit Start at beats the saved resume point
        start = po.start
        end = po.end
        if start is None:
            start = self.resume[1] if (self.resume and
                                       planned[0].num == self.resume[0]) else None
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
                     start=start, end=end, next_frac=nf, extra=m)

    def refresh_labels(self) -> 'Session':
        """Re-pull the episode labels after the provider view changed."""
        self.labels = dict(self.provider.episodes())
        return self

    def stop(self):
        self._stop.set()                 # tells the running playlist to end
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


def open_session(src: str, target: str, cfg, http, opts: dict = None,
                 mpv: List[str] = None, *, wait_titles: bool = False,
                 window: int = None, matcher: str = None) -> Session:
    """Build a Session for (src, target): agp / axp / zoro / tgp / tg.

    - `wait_titles`: block briefly (≤5 s) on missing episode names — the
      curses menu wants them now instead of next launch.
    - `window`/`matcher`: Telegram-only knobs (--window N, -f name matcher).
    """
    from . import features
    from .cli import _link_get, _log_show
    from .metadata import Metadata
    from .titles import TitleService

    opts = dict(opts or {})
    mpv = list(mpv or [])
    t_open = time.monotonic()
    meta = Metadata(cfg, http)
    titles = TitleService(meta, cfg)
    src = (src or 'agp').lower()

    factory = features.get(src, 'provider')
    prov = factory(target, cfg=cfg, opts=opts, window=window,
                   matcher=matcher, http=http)
    prov.load()                       # groups + episode list (per provider)
    groups = getattr(prov, 'groups', None) or []
    labels, mal = prov.titles.open_labels(prov, meta, titles, target,
                                          wait_titles=wait_titles)

    log.cprint(f'>> {prov.title} - {len(labels)} episodes '
               f'({time.monotonic() - t_open:.1f}s)')

    link = _link_get(cfg, prov.title)
    if link is None and not getattr(prov, 'single', False):
        try:
            _log_show(cfg, meta, prov.title)
        except Exception:
            pass
        link = _link_get(cfg, prov.title)

    return Session(src, prov, cfg, http, meta, titles, groups=groups,
                   labels=labels, resume=_resume(cfg, prov.title), opts=opts,
                   mpv=mpv, audio=prov.audio.capable, link=link, mal_id=mal)
