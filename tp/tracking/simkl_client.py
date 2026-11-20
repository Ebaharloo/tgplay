"""tp.tracking.simkl_client - the ONE Simkl REST client.

`SimklAccount` already owns the device login, the single client_id, the token
refresh and every /sync /scrobble /playback /anime call, so this client is that
object plus the keyless CDN feeds (schedule, trending). One client_id, one
refresh path, one place to look.
"""
import json
import urllib.parse

from ..http import _quiet_close
from ..simkl_account import (API, APP, VER, STATUSES, SimklAccount,  # noqa
                             SimklError)

CDN = 'https://data.simkl.in'
CAL = f'{CDN}/calendar/v2/anime.json'


def _params(client_id=None):
    return {'client_id': client_id or '', 'app-name': APP, 'app-version': VER}


def feed(http, url, client_id=None):
    """One CDN JSON file (no auth); raises on failure so callers can keep
    their cache."""
    u = url + '?' + urllib.parse.urlencode(_params(client_id))
    r = http.open(http.request(u, headers={'User-Agent': f'{APP}/{VER}'}))
    try:
        d = json.load(r)
    finally:
        _quiet_close(r)
    return d


class SimklClient(SimklAccount):
    def __init__(self, cfg, http=None, client_id=None):
        super().__init__(cfg, http)
        if client_id:
            self.client_id = client_id

    # --- CDN schedule -----------------------------------------------------
    def schedule(self):
        """The raw v2 calendar file: {'metadata': {...}, 'calendar': [...]}."""
        d = feed(self.http, CAL, self.client_id)
        return d if isinstance(d, dict) else {}

    def calendar(self, days=14, ids=None):
        """Episodes airing from today to `days` ahead, soonest first.

        `days=0` is today (what /anime/airing returns); `ids` limits the rows
        to those Simkl ids (None = every show in the feed)."""
        from datetime import date, datetime
        d = self.schedule()
        meta = d.get('metadata') or {}
        want = {int(x) for x in ids or [] if str(x).isdigit()}
        today = date.today()
        out = []
        for e in d.get('calendar') or []:
            if want and e.get('simkl_id') not in want:
                continue
            try:
                when = datetime.fromisoformat(
                    str(e.get('date')).replace('Z', '+00:00')
                ).astimezone().date()
            except Exception:
                continue
            if when < today or (when - today).days > days:
                continue
            ep = e.get('episode') or {}
            m = meta.get(str(e.get('simkl_id'))) or {}
            ids_ = m.get('ids') or {}
            out.append({'title': m.get('title') or '',
                        'simkl': e.get('simkl_id'), 'mal': ids_.get('mal'),
                        'air_date': e.get('date'),
                        'next_ep': ep.get('episode'),
                        'ep_title': ep.get('title'),
                        'kind': 'today' if when == today else 'upcoming'})
        out.sort(key=lambda x: str(x.get('air_date')))
        return out

    def trending(self):
        d = feed(self.http, f'{CDN}/discover/trending/anime/today_100.json',
                 self.client_id)
        return [r for r in (d if isinstance(d, list) else [])
                if isinstance(r, dict)]

    def connected(self):
        return self.logged_in()
