"""Shared fakes for the tp.tracking tests: a temp cfg + a dead/live Simkl."""
import os


class Cfg:
    """Config-like object rooted in a tmp dir (only the tracking paths)."""

    def __init__(self, d):
        self.d = str(d)

    def _p(self, name):
        return os.path.join(self.d, name)

    def __getattr__(self, name):
        if name in ('watched', 'progress', 'simkl_activities', 'simkl_queue',
                    'simkl_auth', 'anilist_auth', 'anilist_ids', 'characters',
                    'simkl_library'):
            return self._p(name + '.json')
        raise AttributeError(name)


class FakeSimkl:
    """Records the calls a real SimklAccount would receive."""

    def __init__(self, dead=False):
        self.dead = dead
        self.calls = []
        self.rows = {}
        self.stamp = 'A1'
        self.playbacks = []
        self.schedule_rows = []

    def logged_in(self):
        return True

    def activities(self):
        return {'all': self.stamp}

    def watched(self, ids):
        return self.rows.get((ids or {}).get('mal')
                             or (ids or {}).get('simkl'), [])

    def _do(self, name, *args):
        if self.dead:
            raise RuntimeError('network down')
        self.calls.append((name, args))
        return {'added': {'episodes': 1}}

    def mark_episode_watched(self, ids, season, ep):
        return self._do('mark_episode_watched', ids, season, ep)

    def unmark_episode_watched(self, ids, season, ep):
        return self._do('unmark_episode_watched', ids, season, ep)

    def mark_season_watched(self, ids, season):
        return self._do('mark_season_watched', ids, season)

    def unmark_season_watched(self, ids, season):
        return self._do('unmark_season_watched', ids, season)

    def mark_show_complete(self, ids):
        return self._do('mark_show_complete', ids)

    def unmark_show_complete(self, ids):
        return self._do('unmark_show_complete', ids)

    def add_to_list(self, ids, status):
        self._do('add_to_list', ids, status)
        return True

    def rate(self, ids, rating):
        self._do('rate', ids, rating)
        return True

    def unrate(self, ids):
        self._do('unrate', ids)
        return True

    def ratings(self, rating=None):
        self.calls.append(('ratings', (rating,)))
        return [{'simkl': 1, 'user_rating': 9}]

    def scrobble(self, action, ids, num, season=1, progress=0):
        return self._do('scrobble', action, ids, num, progress)

    def playback(self):
        return list(self.playbacks)

    def calendar(self, days=0, ids=None):
        rows = self.schedule_rows
        want = set(ids or [])
        return [r for r in rows if not want or r.get('simkl') in want]

    def trending(self):
        return [{'title': 'Trending', 'simkl': 1, 'kind': 'trending'}]

    def clear_playback(self, pid):
        self.calls.append(('clear_playback', (pid,)))
        return True


class FakeAniList:
    def __init__(self):
        self.calls = []

    def enabled(self):
        return True

    def token(self):
        return 'tok'

    def save_progress(self, mid, watched, total=None, token=None,
                      status=None):
        self.calls.append(('save_progress', mid, watched, status))
        return {'progress': watched}

    def set_status(self, mid, status, progress=None, token=None):
        self.calls.append(('set_status', mid, status))
        return {'status': status}
