"""tp.features.search - title search, one object per source.

Every hit keeps the `{'title', 'url', 'source'}` contract; the url routes
back through `cli_all.route` (`axp:<slug>`, `zoro:<slug>`, ...).
"""
from abc import ABC
from typing import List


class Search(ABC):
    def search(self, query: str, http=None, limit: int = 12) -> List[dict]:
        raise NotImplementedError


class AgpSearch(Search):
    """AnimeGate: works logged-out too."""
    kind = 'agp'

    def search(self, query, http=None, limit=12):
        from ..providers.animegate import search as mod_search
        return mod_search(query, http=http, limit=limit)


class AxpSearch(Search):
    """AnimeX: GraphQL, carries malId/anilistId on every hit."""
    kind = 'axp'

    def search(self, query, http=None, limit=12):
        from ..providers.animex import search as mod_search
        return mod_search(query, http=http, limit=limit)


class ZoroSearch(Search):
    """HiAnime: site search over the first mirror that answers."""
    kind = 'zoro'

    def search(self, query, http=None, limit=12):
        from ..providers.zoro import ZoroProvider
        prov = ZoroProvider(http=http)
        out: List[dict] = []
        for slug, name in prov.search(query):
            out.append({'title': name, 'url': f'zoro:{slug}', 'source': 'zoro'})
            if len(out) >= limit:
                break
        return out
