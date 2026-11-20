"""tp.tracking.history - recent rows for the history table."""


class HistorySync:
    policy = 'first'

    def __init__(self, cfg, http=None, client=None):
        self.cfg = cfg
        self.http = http
        self.client = client

    def recent(self, limit=15):
        """Recently watched rows, newest first (one library read, cached)."""
        try:
            from ..library import overview        # lazy: library imports us
            rows = overview(self.cfg, self.http,
                            hist_limit=limit).get('hist') or []
        except Exception:
            return []
        rows.sort(key=lambda e: str(e.get('last_watched') or ''), reverse=True)
        return rows[:limit]
