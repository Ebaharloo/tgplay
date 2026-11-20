"""tp.tracking.wiki - read-only cast/covers/relations.

Fandom + Bangumi + the AniList cast pages behind one object; cache-first, so
a menu pick is instant and the network refresh never blocks the window.
"""
from ..characters import CharactersService


class CastSync:
    policy = 'all'

    def __init__(self, cfg, http=None, bangumi=None):
        self.cfg = cfg
        self.http = http
        self.service = CharactersService(cfg, http, bangumi=bangumi)

    def cached(self, mal_id=None, title=None):
        try:
            return self.service.cached(mal_id, title)
        except Exception:
            return None

    def fetch(self, mal_id=None, title=None):
        try:
            return self.service.fetch(mal_id, title)
        except Exception:
            return None

    def relations(self, simkl_id):
        from ..simkl_extra import SimklExtra
        try:
            return SimklExtra(self.cfg, self.http).relations(simkl_id)
        except Exception:
            return []
