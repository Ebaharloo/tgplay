"""tp.tracking - the tracking REGISTRY and the one façade consumers use.

Same shape as `tp.features`: one class per feature, one subclass per service,
ONE table naming services, and consumers ask the façade for a feature instead
of importing a client. `FanoutSync` holds the policy per feature in one place:
watched goes to every service, scrobble/resume/calendar to the first one that
can.
"""
from ..config import Config
from .. import log as _log
from .anilist_client import AniListClient, Tracker
from .calendar import CalendarSync
from .history import HistorySync
from .lists import ListStatusSync
from .local_store import LocalStore
from .ratings import RatingSync
from .resume import ResumeSync
from .scrobble import ScrobbleSync
from .simkl_client import SimklClient
from .watched import (AniListWatched, LocalWatched, SimklWatched,
                      WatchedSync)
from .wiki import CastSync

REGISTRY = {
    'watched': {'local': LocalWatched, 'simkl': SimklWatched,
                'anilist': AniListWatched},
    'lists': {'simkl': ListStatusSync, 'anilist': ListStatusSync},
    'ratings': {'simkl': RatingSync},
    'scrobble': {'simkl': ScrobbleSync},
    'resume': {'simkl': ResumeSync},
    'calendar': {'simkl': CalendarSync},
    'history': {'simkl': HistorySync},
    'cast': {'anilist': CastSync},
}

# ONE policy per feature: who receives a write
POLICY = {'watched': 'all', 'lists': 'all', 'scrobble': 'first',
          'resume': 'first', 'ratings': 'first', 'calendar': 'first',
          'history': 'first', 'cast': 'all'}


def get(service, feature):
    """The feature class for (service, feature); None when it lacks one."""
    return REGISTRY.get(feature, {}).get(service)


class FanoutSync:
    """Run one call across the services a feature's policy names."""

    def __init__(self, feature, services, policy=None):
        self.feature = feature
        self.policy = policy or POLICY.get(feature, 'first')
        self.services = [s for s in services if s is not None and s.enabled()]

    def __call__(self, method, *args, **kwargs):
        out = []
        for s in self.services:
            fn = getattr(s, method, None)
            if fn is None:
                continue
            try:
                got = fn(*args, **kwargs)
            except Exception as ex:
                _log.cprint(f'track: {type(s).__name__} {method} failed ({ex})')
                continue
            if got is not None:
                out.append(got)
            if self.policy == 'first':
                break
        return out


class Tracking:
    """One live tracking rig: clients, queue, sync worker, features."""

    def __init__(self, cfg=None, http=None, on_status=None):
        self.cfg = cfg or Config()
        self.client = SimklClient(self.cfg, http)
        self.anilist = AniListClient(self.cfg, http)
        self.store = LocalStore(self.cfg)
        self.queue = _queue(self.cfg)
        self.syncer = _syncer(self.queue, self.client, self.anilist,
                              on_status)
        self.watched = WatchedSync(self.cfg, self.queue, self.client,
                                   self.anilist, self.store)
        self.lists = ListStatusSync(self.queue, self.client, self.anilist)
        self.ratings = RatingSync(self.queue, self.client)
        self.scrobble = ScrobbleSync(self.client, self.watched)
        self.resume = ResumeSync(self.client)
        self.calendar = CalendarSync(self.cfg, http, self.client)
        self.history = HistorySync(self.cfg, http, self.client)
        self.cast = CastSync(self.cfg, http)
        self.features = {'watched': self.watched, 'lists': self.lists,
                         'ratings': self.ratings, 'scrobble': self.scrobble,
                         'resume': self.resume, 'calendar': self.calendar,
                         'history': self.history, 'cast': self.cast}

    # --- lifecycle --------------------------------------------------------
    def start(self):
        self.syncer.start()
        return self

    def stop(self):
        self.syncer.stop()

    def pull(self, id_map=None, keys=None):
        """Pull Simkl watched state into the local store (worker thread)."""
        return self.watched.pull(id_map, keys)

    def connected(self):
        try:
            return bool(self.client.logged_in())
        except Exception:
            return False


def _queue(cfg):
    from ..simkl_sync import SyncQueue
    return SyncQueue(cfg.simkl_queue)


def _syncer(queue, client, anilist, on_status):
    from ..simkl_sync import AniListPusher, SimklPusher, Syncer
    return Syncer(queue, pushers={'simkl': SimklPusher(client),
                                  'anilist': AniListPusher(anilist)},
                  on_status=on_status)


class TrackingTracker:
    """Playlist adapter: the same watched/scrobble/resume features, no client
    call of its own. `make_tracker` returns this so playback and the GUI menu
    write through ONE path (local first, then the queue)."""

    def __init__(self, cfg, http=None):
        self.t = _rig(cfg, http)
        self._match = _Matcher(cfg, http)

    def enabled(self):
        return self.t.connected()

    def _ids(self, title, mal=None, anilist=None):
        ids = {k: v for k, v in (('mal', mal), ('anilist', anilist)) if v}
        return ids or self._match.ids(title)

    def mark_watched(self, title, num, ask=False, mal=None, anilist=None):
        ids = self._ids(title, mal, anilist)
        if not ids:
            _log.cprint(f'track: no id for "{title}" — not synced')
            return None
        key = self.t.watched.key(title, ids)
        self.t.watched.finished(key, ids, num)
        self.t.syncer.wake()
        return ids

    def scrobble(self, title, num, progress, action='start', mal=None,
                 anilist=None):
        ids = self._ids(title, mal, anilist)
        if not ids:
            return None
        return self.t.scrobble.send(action, ids, num, progress)

    def resume(self, title, num, mal=None, anilist=None):
        return self.t.resume.read(num, self._ids(title, mal, anilist))

    def forget(self, title, num, mal=None, anilist=None):
        return self.t.resume.clear(num, self._ids(title, mal, anilist))


_RIGS = {}


def _rig(cfg, http=None):
    """One Tracking rig per config dir: a playlist per episode must not spawn
    a worker thread (or a second queue) every time."""
    key = getattr(cfg, 'conf', None) or id(cfg)
    rig = _RIGS.get(key)
    if rig is None:
        rig = _RIGS[key] = Tracking(cfg, http).start()
    return rig


class _Matcher:
    """Title -> ids from the Simkl library (the one fuzzy match we keep)."""

    def __init__(self, cfg, http=None):
        self.cfg = cfg
        self.http = http
        self._rows = None

    def ids(self, title):
        from ..simkl_account import SimklTracker
        try:
            return SimklTracker(self.cfg, self.http)._ids(title)
        except Exception:
            return {}


def make_tracker(cfg, http=None, sync=True):
    """The playlist's tracker, or None when syncing is off."""
    if not sync:
        return None
    try:
        t = TrackingTracker(cfg, http)
    except Exception:
        return None
    return t if t.enabled() else None


class MultiTracker:
    """Compat: fan one call over a list of trackers (playlist tests use it).

    New code uses `Tracking`/`FanoutSync`; this stays so the playlist's
    tracker-shaped interface has a second implementation for tests.
    """

    def __init__(self, trackers):
        self.trackers = [t for t in (trackers or []) if t is not None]

    def enabled(self):
        return any(_safe(t.enabled) for t in self.trackers)

    def mark_watched(self, title, num, ask=False, mal=None, anilist=None):
        done = []
        for t in self.trackers:
            if _safe(t.enabled) and _safe(t.mark_watched, title, num,
                                          mal=mal, anilist=anilist):
                done.append(type(t).__name__)
        return done

    def scrobble(self, title, num, progress, action='start', mal=None,
                 anilist=None):
        for t in self.trackers:
            fn = getattr(t, 'scrobble', None)
            if fn is not None and _safe(t.enabled):
                return _safe(fn, title, num, progress, action=action,
                             mal=mal, anilist=anilist)
        return None

    def resume(self, title, num, mal=None, anilist=None):
        for t in self.trackers:
            fn = getattr(t, 'resume', None)
            if fn is not None and _safe(t.enabled):
                got = _safe(fn, title, num, mal=mal, anilist=anilist)
                if got:
                    return got
        return None

    def forget(self, title, num, mal=None, anilist=None):
        for t in self.trackers:
            fn = getattr(t, 'forget', None)
            if fn is not None and _safe(t.enabled):
                _safe(fn, title, num, mal=mal, anilist=anilist)


def _safe(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as ex:
        _log.cprint(f'track: {getattr(fn, "__name__", "call")} failed ({ex})')
        return None
