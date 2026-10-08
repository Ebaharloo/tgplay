"""tp.providers.base - the Provider interface."""
from abc import ABC, abstractmethod
from typing import Dict

from ..sources import MediaSource


class Provider(ABC):
    """A streamable catalog: episodes by number, and a fresh byte source each
    time (signed links expire, so a source is built per play, not cached)."""

    title: str = ''

    @abstractmethod
    def episodes(self) -> Dict[int, str]:
        """{episode number: label}, ascending."""

    @abstractmethod
    def stream(self, num: int) -> MediaSource:
        """A byte source for episode `num` (re-resolves the link)."""

    def display_name(self, num: int):
        """Optional human/file name for an episode (None -> derive it)."""
        return None
