"""tp.tracking.watched - watched state: local first, one durable queue out.

ONE entry point for every watched change (GUI menu, playback finish, pull
merge). The local store is written first, then the change is queued per
service; the Syncer pushes it. Nothing is lost when the network is down.

The local unmark wins over the remote: `local_store` keeps a tombstone per
unmarked episode, so a pull can never resurrect it (it re-queues the remove
instead).
"""
from .. import watched as _w
from ..config import load_json
from ..simkl_sync import EP, SEASON, SHOW, pull_done, pull_gate, remote_watched
from .local_store import LocalStore

ALL = '*'           # fan-out policy for this feature: every service


class WatchedService:
    """One service's watched writer (the registry picks the enabled ones)."""

    name = ''

    def __init__(self, client=None, cfg=None):
        self.client = client
        self.cfg = cfg

    def enabled(self) -> bool:
        return False


class LocalWatched(WatchedService):
    name = 'local'

    def enabled(self):
        return True


class SimklWatched(WatchedService):
    name = 'simkl'

    def enabled(self):
        try:
            return bool(self.client and self.client.logged_in())
        except Exception:
            return False


class AniListWatched(WatchedService):
    name = 'anilist'

    def enabled(self):
        try:
            return bool(self.client and (self.client.enabled()
                                         or self.client.token()))
        except Exception:
            return False


class WatchedSync:
    """local store + queue for one watched change; the pull side too."""

    policy = ALL

    def __init__(self, cfg, queue, client=None, anilist=None,
                 store=None):
        self.cfg = cfg
        self.queue = queue
        self.store = store or LocalStore(cfg)
        self.services = [s for s in (LocalWatched(cfg=cfg),
                                     SimklWatched(client, cfg),
                                     AniListWatched(anilist, cfg))
                         if s.enabled()]
        self.client = client
        self.anilist = anilist

    # --- state ------------------------------------------------------------
    def key(self, title, ids=None):
        return _w.key_for(title, ids)

    def state(self, key):
        return self.store.state(key)

    def rows(self, key):
        return self.store.state(key)

    # --- write ------------------------------------------------------------
    def change(self, key, kind, num, nums, watched=None):
        """Apply one menu choice locally (the caller queues it)."""
        return self.store.change(key, kind, num, nums, watched)

    def queue_change(self, kind, watched, info, ids):
        """Queue one local change for every service that takes it."""
        ids = {k: v for k, v in (ids or {}).items() if v}
        if not ids:
            return 0
        ep = info.get('num')
        nums = [int(n) for n in (info.get('nums') or [])]
        if kind == 'episode':
            return self._put(ids, EP, ep, watched, season=1) + (
                self._put(ids, EP, ep, watched, season=1, svc='anilist'))
        if kind in ('season', 'season_unwatched'):
            # native season call: one request instead of N + Simkl's 20s lock
            n = self._put(ids, SEASON, None, watched, season=1)
            if watched:                       # AniList progress only counts up
                n += self._put(ids, SEASON, None, watched, season=1,
                               svc='anilist', last=max(nums or [1]))
            return n
        if kind == 'till_here':
            up = [n for n in nums if ep is not None and n <= int(ep)]
            return sum(self._put(ids, EP, x, True, season=1) for x in up) + sum(
                self._put(ids, EP, x, True, season=1, svc='anilist')
                for x in up)
        n = self._put(ids, SHOW, None, watched)
        return n

    def _put(self, ids, kind, ep, watched, season=1, svc='simkl', **extra):
        # queue even when the service is offline/unconfigured: the queue file
        # is the durable record and drains once a token exists
        if svc == 'anilist' and not ids.get('anilist'):
            return 0
        self.queue.put(ids, season, ep, watched, kind=kind, svc=svc,
                       **extra)
        return 1

    def _logged_in(self):
        try:
            return self.client.logged_in()
        except Exception:
            return False

    def finished(self, key, ids, num):
        """Playback finished one episode: local mark, then queue it."""
        key = key or _w.key_for('', ids)
        self.store.set_episode(key, num, True)
        return self._put(ids, EP, num, True, season=1) + (
            self._put(ids, EP, num, True, season=1, svc='anilist') or 0)

    # --- read -------------------------------------------------------------
    def pull(self, id_map=None, keys=None):
        """Merge Simkl's watched state in; tombstones keep local unmarks.

        `id_map(key)` supplies the ids for a store key. Returns how many
        episodes were added locally.
        """
        if not self.client or not self._logged_in():
            return 0
        keys = keys or [k for k in load_json(self.store.path(), {}) or {}]
        snap = ''
        if not id_map:
            moved = True
        else:
            try:
                moved, snap = pull_gate(self.client, self.cfg.simkl_activities)
            except Exception:
                moved = True
        if not moved and keys:
            return 0
        added = 0
        for key in keys:
            ids = (id_map(key) if id_map else _ids_of(key)) or {}
            if not ids:
                continue
            try:
                remote = remote_watched(self.client, ids)
            except Exception:
                continue
            local = self.store.state(key)
            for (season, ep), _ts in remote.items():
                if ep in local['tomb']:
                    # the user unmarked this here: keep it unmarked, tell Simkl
                    self.queue.put(ids, season, ep, False)
                    continue
                if ep not in local['eps']:
                    self.store.set_episode(key, ep, True)
                    added += 1
        if snap:
            pull_done(self.cfg.simkl_activities, snap)
        return added


def _ids_of(key):
    """{'mal': 21} from 'mal:21' / 'simkl:7'; a title key carries no ids."""
    k, _, v = (key or '').partition(':')
    if k in ('simkl', 'mal', 'anilist') and v.isdigit():
        return {k: int(v)}
    return {}
