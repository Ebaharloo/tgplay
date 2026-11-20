"""tp.tracking.scrobble - playback progress (start/pause/stop).

Simkl is the only scrobbler, so the policy is `first`. This object owns the
two rules that used to live in three places: a stop at >=80% is a watched
mark, and Simkl's 20s per-user write lock is paced here instead of firing a
request the API will refuse.
"""
import time

WATCHED_PCT = 80.0
LOCK = 20.0             # Simkl's per-user write lock, in seconds


class ScrobbleSync:
    policy = 'first'

    def __init__(self, client=None, watched=None, clock=time.monotonic):
        self.client = client
        self.watched = watched
        self.clock = clock
        self._last = 0.0

    def enabled(self) -> bool:
        try:
            return bool(self.client and self.client.logged_in())
        except Exception:
            return False

    def send(self, action, ids, num, progress, season=1):
        """One /scrobble call; returns the answer or None when skipped."""
        if not self.enabled() or not ids:
            return None
        now = self.clock()
        if action != 'start' and self._last and now - self._last < LOCK:
            return {'skipped': 'lock'}      # too soon: the next stop carries it
        try:
            res = self.client.scrobble(action, ids, num, season=season,
                                       progress=progress)
        except Exception:
            return None
        self._last = now
        if action == 'stop' and _pct(progress) >= WATCHED_PCT and self.watched:
            self.watched.finished(None, ids, int(num))
        return res

    def due(self, progress) -> bool:
        return _pct(progress) >= WATCHED_PCT


def _pct(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0
