"""tp.simkl_sync - offline-first push of watched changes to Simkl.

A local watched change is written to a queue file FIRST (`pending_sync.json`
next to progress.json, see `Config.simkl_queue`), then a daemon worker pushes
it. Nothing is lost while offline, when Simkl answers 500, or when the app is
killed: the queue survives restarts and is drained on start and every
`interval` seconds.

The queue is keyed by (show, season, episode), so a later write replaces the
earlier one: marking ep 5 then unmarking it before a flush sends only the
final state. Pushes go through `SimklAccount._api` (it refreshes the token on
a 401, same path as tp/simkl_extra.py); one failing item is kept and the rest
still go out.

No Qt here: the GUI passes `on_status` and shows it non-blocking.
"""
import threading
import time
from typing import Callable, Dict, Optional, Tuple

from .config import load_json, save_json
from .simkl_account import SimklAccount

EP, SEASON, SHOW = 'episode', 'season', 'show'
IDS = ('simkl', 'mal', 'anilist')

# the GUI thread writes the queue while the worker drains it: one lock, and
# every write is a locked read-modify-write (the simkl_extra.py convention)
_LOCK = threading.Lock()


def show_key(ids) -> str:
    """Stable key for a show, best id first (so it does not change between
    a queue write and a later one that carries more ids)."""
    for k in IDS:
        if (ids or {}).get(k):
            return f'{k}:{ids[k]}'
    return ''


def queue_key(ids, season=None, ep=None, kind=EP) -> str:
    base = show_key(ids) or f'title:{ids.get("title", "")}'
    if kind == EP:
        return f'{base}|s{int(season)}|e{int(ep)}'
    if kind == SEASON:
        return f'{base}|s{int(season)}'
    return f'{base}|all'


class SyncQueue:
    """pending_sync.json = {key: item}. One state per key, last write wins."""

    def __init__(self, path: str):
        self.path = path

    def _read(self) -> Dict[str, dict]:
        d = load_json(self.path, {})
        return d if isinstance(d, dict) else {}

    def put(self, ids, season=None, ep=None, watched=True,
            kind=EP) -> str:
        key = queue_key(ids, season, ep, kind)
        item = {'ids': {k: ids[k] for k in IDS if (ids or {}).get(k)},
                'kind': kind, 'watched': bool(watched),
                'at': time.time(), 'tries': 0, 'error': ''}
        if kind in (EP, SEASON):
            item['season'] = int(season)
        if kind == EP:
            item['ep'] = int(ep)
        with _LOCK:
            d = self._read()
            d[key] = item
            save_json(self.path, d)
        return key

    def items(self) -> Dict[str, dict]:
        with _LOCK:
            return self._read()

    def drop(self, key: str, at=None) -> None:
        """Remove a pushed item. `at` guards a newer state queued while the
        push was in flight: that one has not been sent, so it stays."""
        with _LOCK:
            d = self._read()
            cur = d.get(key)
            if cur is None or (at is not None and cur.get('at') != at):
                return
            d.pop(key, None)
            save_json(self.path, d)

    def bump(self, key: str, error: str = '', at=None) -> None:
        with _LOCK:
            d = self._read()
            cur = d.get(key)
            if cur is None or (at is not None and cur.get('at') != at):
                return
            cur['tries'] = int(cur.get('tries', 0)) + 1
            cur['error'] = str(error)[:200]
            save_json(self.path, d)

    def __len__(self) -> int:
        return len(self.items())


class SimklPusher:
    """item -> one SimklAccount history call (raises SimklError on failure)."""

    # (kind, watched) -> (account method, extra positional args)
    CALLS = {
        (EP, True): ('mark_episode_watched', ('season', 'ep')),
        (EP, False): ('unmark_episode_watched', ('season', 'ep')),
        (SEASON, True): ('mark_season_watched', ('season',)),
        (SEASON, False): ('unmark_season_watched', ('season',)),
        (SHOW, True): ('mark_show_complete', ()),
        (SHOW, False): ('unmark_show_complete', ()),
    }

    def __init__(self, acc: SimklAccount):
        self.acc = acc

    def __call__(self, item: dict) -> None:
        name, args = self.CALLS[(item['kind'], bool(item['watched']))]
        getattr(self.acc, name)(item['ids'],
                                *[item[a] for a in args])


class Syncer:
    """Drains the queue on a daemon thread; never blocks the caller."""

    def __init__(self, queue: SyncQueue, acc: Optional[SimklAccount] = None,
                 push: Optional[Callable[[dict], None]] = None,
                 interval: float = 60.0,
                 on_status: Optional[Callable[[dict], None]] = None):
        self.queue = queue
        self.push = push or (SimklPusher(acc) if acc is not None else None)
        self.interval = interval
        self.on_status = on_status
        self.last_error = ''
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def wake(self) -> None:
        """Ask the loop to flush now (a new change was just queued)."""
        self._wake.set()

    def flush(self) -> dict:
        """One pass over the queue: push, drop what Simkl accepted, keep the
        failures. Returns {'sent', 'failed', 'pending'}."""
        sent = failed = 0
        if self.push is None:            # not connected: keep everything queued
            return {'sent': 0, 'failed': 0, 'pending': len(self.queue)}
        for key, item in self.queue.items().items():
            try:
                self.push(item)
            except Exception as ex:
                failed += 1
                self.last_error = str(ex)
                self.queue.bump(key, ex, at=item.get('at'))
                continue
            sent += 1
            self.queue.drop(key, at=item.get('at'))
        res = {'sent': sent, 'failed': failed, 'pending': len(self.queue)}
        if (sent or failed) and self.on_status:
            try:
                self.on_status(res)
            except Exception:
                pass
        return res

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='simkl-sync')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.flush()
            except Exception as ex:      # a broken queue file must not kill it
                self.last_error = str(ex)
            # a change queued while flushing wakes us at once; otherwise poll
            self._wake.wait(self.interval)


# --- pull direction --------------------------------------------------------
def _ts(value) -> float:
    """ISO date / epoch / None -> epoch seconds (0 when unknown)."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        from datetime import datetime
        s = str(value).replace('Z', '+00:00')
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def remote_watched(acc: SimklAccount, ids: dict) -> Dict[Tuple[int, int], float]:
    """{(season, episode): watched_at} for one show, from Simkl.

    One POST /sync/watched (extended=episodes): only this show's episodes come
    back, so a pull no longer downloads the whole library with every episode.
    """
    if not any((ids or {}).get(k) for k in IDS):
        return {}
    out: Dict[Tuple[int, int], float] = {}
    for row in acc.watched({k: ids[k] for k in IDS if ids.get(k)}):
        for s in row.get('seasons') or []:
            if not isinstance(s, dict):
                continue
            for e in s.get('episodes') or []:
                if (isinstance(e, dict) and e.get('number') is not None
                        and e.get('watched', True)):
                    out[(int(s.get('number') or 1), int(e['number']))] = _ts(
                        e.get('last_watched_at') or e.get('watched_at')
                        or e.get('watched-at'))
        if out:
            break
    return out


def pull_gate(acc: SimklAccount, path: str) -> Tuple[bool, str]:
    """(moved, snapshot) from ONE /sync/activities call.

    Simkl bumps the top-level `all` stamp whenever any list changes, so when it
    equals the saved one a per-show pull cannot find anything new."""
    cur = str((acc.activities() or {}).get('all') or '')
    prev = str((load_json(path, {}) or {}).get('all') or '')
    return not (cur and cur == prev), cur


def pull_done(path: str, snapshot: str) -> None:
    """Remember a completed pull, so the next one can be skipped."""
    if snapshot:
        save_json(path, {'all': snapshot})


def reconcile(local: Dict[Tuple[int, int], float],
              remote: Dict[Tuple[int, int], float]
              ) -> Tuple[Dict[Tuple[int, int], float], list]:
    """Merge pulled Simkl state into local. Newer timestamp wins; a key both
    sides have with different states is returned as a conflict for the log."""
    merged, conflicts = dict(local), []
    for key, rts in remote.items():
        lts = local.get(key)
        if lts is None:
            merged[key] = rts
        elif abs(float(lts) - float(rts)) > 1.0:
            merged[key] = max(float(lts), float(rts))
            conflicts.append({'episode': key, 'local': lts, 'remote': rts,
                              'kept': 'local' if lts > rts else 'remote'})
    return merged, conflicts
