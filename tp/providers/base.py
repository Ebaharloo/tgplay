"""tp.providers.base - the Provider interface."""
from abc import ABC, abstractmethod
from typing import Dict

from ..features.audio import NoAudio
from ..features.quality import NoQuality
from ..features.servers import Servers
from ..features.sizes import NoSizes
from ..sources import MediaSource


class Provider(ABC):
    """A streamable catalog: episodes by number, and a fresh byte source each
    time (signed links expire, so a source is built per play, not cached).

    Per-source behaviour lives in feature objects (`audio`, `quality`, ...),
    not in `src ==` checks at the call sites."""

    title: str = ''
    audio = NoAudio()        # dub/sub choice (NoAudio = none, e.g. tg/agp)
    quality = NoQuality()    # server/rendition menu shape
    servers = Servers()      # server-selection policy
    sizes = NoSizes()        # file-size knowledge (NoSizes = HLS sources)

    @abstractmethod
    def episodes(self) -> Dict[int, str]:
        """{episode number: label}, ascending."""

    @abstractmethod
    def stream(self, num: int) -> MediaSource:
        """A byte source for episode `num` (re-resolves the link)."""

    def select(self, quality=None) -> 'Provider':
        """Apply the chosen quality/server label (no-op for single-quality
        sources; re-selecting a narrowed Telegram view would renumber it)."""
        return self

    def size(self, num: int) -> int:
        """File size of episode `num` in bytes (0 = unknown/not fixed,
        e.g. the HLS DirectSource AnimeX plays through mpv)."""
        return 0

    def display_name(self, num: int):
        """Optional human/file name for an episode (None -> derive it)."""
        return None


class NoServersYet(ValueError):
    """The page exists but offers no playable servers yet (movie too new,
    region link, ...) — a user-readable message, not a stacktrace."""
