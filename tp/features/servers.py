"""tp.features.servers - server selection policy, one object per source.

`select()` at play time re-applies the user's server/quality choice; Telegram
views are already narrowed and numbered at build time, so re-selecting would
renumber them - TgServers says so with `reselects = False`.
"""
from abc import ABC


class Servers(ABC):
    reselects: bool = True     # safe to select() again at play time?

    def rotate(self, provider) -> bool:
        """Try the provider's next server (False = nothing to rotate to)."""
        rot = getattr(provider, 'rotate', None)
        return bool(rot()) if callable(rot) else False


class TgServers(Servers):
    """Telegram: a narrowed view; select() would renumber the episodes."""
    reselects = False


class AgpServers(Servers):
    """AnimeGate: download-link groups, re-selectable."""


class AxpServers(Servers):
    """AnimeX: sub/dub servers, re-selectable and rotatable on failure."""


class ZoroServers(Servers):
    """HiAnime: named embed servers, re-selectable; stream() walks them."""
