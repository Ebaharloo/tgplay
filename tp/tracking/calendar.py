"""tp.tracking.calendar - ONE schedule feed + the derived date views.

The v2 CDN file is fetched through `simkl_client` (one implementation, cached
an hour); `library.overview`, `recent.py` and `simkl_extra.calendar` all read
their dates from here now.
"""
import time

FEED_TTL = 3600
_FEED = {}          # one process-wide copy: the feed changes hourly


class CalendarSync:
    policy = 'first'

    def __init__(self, cfg, http=None, client=None):
        self.cfg = cfg
        self.http = http
        self.client = client

    # --- raw feed ---------------------------------------------------------
    def calendar(self, days=0):
        """Schedule rows (title, simkl, air_date, next_ep, kind)."""
        stamp, rows = _FEED.get('calendar') or (0.0, [])
        if rows and time.time() - stamp < FEED_TTL:
            return _window(rows, days)
        try:
            rows = self.client.calendar(400) if self.client else []
        except Exception:
            return _window(rows, days)          # stale rows beat nothing
        if rows:
            _FEED['calendar'] = (time.time(), rows)
        return _window(rows, days)

    def trending(self):
        stamp, rows = _FEED.get('trending') or (0.0, [])
        if rows and time.time() - stamp < FEED_TTL:
            return rows
        try:
            rows = self.client.trending() if self.client else []
        except Exception:
            return rows
        if rows:
            _FEED['trending'] = (time.time(), rows)
        return rows

    # --- derived views ----------------------------------------------------
    def overview(self, aired_days=7, cal_days=14, hist_limit=15):
        """The sidebar payload: cal / rem / hist / rows from ONE library read."""
        from ..library import overview
        return overview(self.cfg, self.http, aired_days, cal_days, hist_limit)

    @staticmethod
    def recently_aired(rows, days=7):
        """Library rows whose last air date falls in the last `days`."""
        from datetime import date, timedelta
        today = date.today()
        cut = (today - timedelta(days=days)).isoformat()
        out = []
        for e in rows or []:
            d = str(e.get('air_date') or '')[:10]
            if d and cut <= d < today.isoformat():
                out.append(dict(e, kind='aired'))
        out.sort(key=lambda e: str(e['air_date']), reverse=True)
        return out

    @staticmethod
    def future(rows):
        """Rows with a known air date today or later, soonest first."""
        from datetime import date
        today = date.today().isoformat()
        out = [e for e in rows or []
               if str(e.get('air_date') or '')[:10] >= today]
        out.sort(key=lambda e: str(e['air_date']))
        return out


def _window(rows, days):
    from datetime import date, datetime
    today = date.today()
    out = []
    for r in rows:
        try:
            when = datetime.fromisoformat(
                str(r.get('air_date')).replace('Z', '+00:00')
            ).astimezone().date()
        except Exception:
            continue
        if when < today or (when - today).days > days:
            continue
        out.append(r)
    return out
