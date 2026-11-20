"""tp.tracking.lists - list status (add/drop/plan/hold/complete).

One entry point for the three GUI call sites. The write goes through the same
durable queue as watched, for Simkl AND AniList (whose statuses are mapped
here instead of the hardcoded CURRENT/COMPLETED).
"""
from ..simkl_account import STATUSES
from .anilist_client import STATUS_MAP

KIND = 'list'


class ListStatusSync:
    policy = '*'            # every service that takes a list status

    def __init__(self, queue, client=None, anilist=None):
        self.queue = queue
        self.client = client
        self.anilist = anilist

    def set(self, ids, status):
        """Queue one status change; False when the status or ids are bad."""
        if status not in STATUSES:
            raise ValueError(f'unknown list status {status!r}')
        ids = {k: v for k, v in (ids or {}).items() if v}
        if not ids:
            return False
        n = 0
        if self.client is not None and _on(self.client, 'logged_in'):
            self.queue.put(ids, kind=KIND, watched=True, status=status)
            n += 1
        if ids.get('anilist') and self.anilist is not None \
                and _on(self.anilist, 'enabled'):
            self.queue.put(ids, kind=KIND, watched=True, status=status,
                           svc='anilist')
            n += 1
        return bool(n)

    @staticmethod
    def mapping():
        return dict(STATUS_MAP)


def _on(obj, fn):
    try:
        return bool(getattr(obj, fn)())
    except Exception:
        return False
