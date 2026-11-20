"""tp.tracking.resume - cross-device resume points (read / clear).

Absorbs `SimklTracker.resume/forget` and `playlist._resume_point`: one cached
read of /sync/playback and one DELETE, from one object.
"""
import logging

log = logging.getLogger(__name__)


class ResumeSync:
    policy = 'first'

    def __init__(self, client=None):
        self.client = client
        self._rows = None

    def enabled(self) -> bool:
        try:
            return bool(self.client and self.client.logged_in())
        except Exception:
            return False

    def rows(self):
        if self._rows is None and self.enabled():
            try:
                self._rows = self.client.playback() or []
            except Exception:
                self._rows = []
        return self._rows or []

    def read(self, num, ids=None):
        """{'percent': 42.2, 'id': 900} for this episode, or None."""
        want = {str(v) for v in (ids or {}).values() if v}
        if not want:
            return None
        for r in self.rows():
            if r.get('episode') != num:
                continue
            if any(str(r.get(k)) in want for k in ('simkl', 'mal', 'anilist')):
                return {'percent': float(r.get('progress') or 0),
                        'id': r.get('id')}
        return None

    def clear(self, num, ids=None) -> bool:
        """DELETE the resume point for an episode finished here."""
        r = self.read(num, ids)
        if not (r and r.get('id')):
            return False
        ok = self.client.clear_playback(r['id'])
        if ok and self._rows is not None:
            self._rows = [x for x in self._rows if x.get('id') != r['id']]
        return ok

    forget = clear
