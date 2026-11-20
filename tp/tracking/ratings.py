"""tp.tracking.ratings - the 1-10 score (rate / unrate / read).

Ratings used to fire directly from a menu while watched writes queued. They
now take the same durable queue path, and the dead read/unrate calls are
reachable from one object instead of being orphans.
"""
from ..simkl_account import SimklError

RATING = 'rating'
UNRATE = 'unrate'


class RatingSync:
    policy = 'first'            # Simkl only: AniList has no 1-10 score here

    def __init__(self, queue, client=None):
        self.queue = queue
        self.client = client

    def rate(self, ids, rating):
        n = int(rating)
        if not 1 <= n <= 10:
            raise ValueError(f'rating must be 1-10, got {rating!r}')
        ids = {k: v for k, v in (ids or {}).items() if v}
        if not ids or not self._connected():
            return False
        self.queue.put(ids, kind=RATING, watched=True, rating=n)
        return True

    def unrate(self, ids):
        ids = {k: v for k, v in (ids or {}).items() if v}
        if not ids or not self._connected():
            return False
        self.queue.put(ids, kind=UNRATE, watched=True)
        return True

    def read(self, rating=None):
        """The user's own scores straight from Simkl (queued writes excluded)."""
        if self.client is None:
            return []
        try:
            return self.client.ratings(rating)
        except SimklError:
            return []

    def _connected(self):
        try:
            return bool(self.client and self.client.logged_in())
        except Exception:
            return False
