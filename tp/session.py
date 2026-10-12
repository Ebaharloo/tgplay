"""tp.session - a playable "what you're watching" bundle.

A Session owns one provider + the shared services (proxy, cache, skip,
prefetch, player) and knows how to play a chosen episode list. The unified GUI
can load a fresh Session in place when the user searches or pastes a new link,
without restarting the app. This is the OOP seam between "pick a source" and
"the window".
"""
import threading
from typing import Dict, List, Optional

from . import log
from .cache import Cache
from .episodes import Episode
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
                 base_mpv: List[str] = None):
        self.cfg = cfg
        self.http = http
        self.base_opts = dict(base_opts or {})
        self.base_mpv = list(base_mpv or [])

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
                            o, m)


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
                 audio: bool = False, link: Optional[str] = None):
        self.src = src
        self.provider = provider
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
        if self.src == 'axp':
            self.provider.set_audio(o.get('audio') or 'dub')
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
                            prefetcher=self._prefetch, tracker=tracker)
        start = self.resume[1] if (self.resume and planned[0].num == self.resume[0]) else None
        nf = ('cut' if (o.get('nowait') and o.get('cut')) else o.get('next')) \
            if o.get('next') else False
        playlist.run(planned, skip_mode=(o.get('skip') or 'all'),
                     skip_toggle=bool(o.get('skip_toggle')), cut=o.get('cut'),
                     start=start, next_frac=nf, extra=m)

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
                 mpv: List[str] = None) -> Session:
    """Build a Session for (src, target): agp / axp / tgp / tg."""
    from .cli import _link_get, _log_show
    from .metadata import Metadata
    from .titles import TitleService

    opts = dict(opts or {})
    mpv = list(mpv or [])
    meta = Metadata(cfg, http)
    titles = TitleService(meta, cfg)
    src = (src or 'agp').lower()

    if src == 'axp':
        from .providers.animex import AnimeXProvider
        prov = AnimeXProvider(target, quality=opts.get('f'),
                              audio=opts.get('audio') or 'dub', http=http)
        prov.set_audio(opts.get('audio') or 'dub')
        prov.fetch_groups()
        prov.select(opts.get('f'))
        groups = prov.groups
        labels = dict(prov.episodes())
        audio = True
    elif src in ('tg', 'tgp'):
        from .providers.telegram import SingleFileProvider, TelegramProvider
        chat, msg_id = _telegram_target(target)
        if src == 'tg' and msg_id is not None:
            prov = SingleFileProvider(chat, msg_id, cfg.tg_session)
            prov.load()
            labels = dict(prov.episodes())
        else:
            prov = TelegramProvider(chat, session=cfg.tg_session)
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
        mal = _safe_mal(meta, prov.title)
        labels = titles.labels(mal, {n: f'Episode {n}' for n in eps})
        groups = prov.groups
        audio = False
        if mal and any(labels.get(n, '').startswith('Episode ') for n in eps):
            threading.Thread(
                target=lambda: meta.refresh_titles(mal, prov.title),
                daemon=True).start()          # fill missing names next time

    log.cprint(f'>> {prov.title} - {len(labels)} episodes')

    link = _link_get(cfg, prov.title)
    if link is None and src != 'tg':
        try:
            _log_show(cfg, meta, prov.title)
        except Exception:
            pass
        link = _link_get(cfg, prov.title)

    return Session(src, prov, cfg, http, meta, titles, groups=groups,
                   labels=labels, resume=_resume(cfg, prov.title), opts=opts,
                   mpv=mpv, audio=audio, link=link)
