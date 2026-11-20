"""tp.features.sizes - per-episode file sizes, one object per source.

Telegram knows the size from the message document; AnimeGate probes its
signed CDN links once. HLS sources (axp/zoro) have no fixed file size.
"""
from abc import ABC


class Sizes(ABC):
    capable: bool = True     # False = the Size column is '—', never probed

    def size(self, provider, num: int) -> int:
        """Bytes for episode `num` (0 = unknown/not fixed)."""
        return int(provider.size(num) or 0)


class TgSizes(Sizes):
    """Telegram: the real size, read from the document."""


class AgpSizes(Sizes):
    """AnimeGate: probes the signed CDN link once, then caches."""


class NoSizes(Sizes):
    """HLS (axp/zoro): renditions, not files - no size to report."""
    capable = False
