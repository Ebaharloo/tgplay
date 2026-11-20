"""tp.features.audio - the dub/sub choice, one object per source.

A source that has no audio choice (tg/agp) owns a NoAudio object; one that
does (axp/zoro) owns its own Audio subclass. A bug fixed in one source's
object can never break another source's.
"""
from abc import ABC


class Audio(ABC):
    """Whether this source offers dub/sub, and how to apply it at play time."""

    capable: bool = True

    def prepare(self, provider, value):
        """Apply the user's audio choice to the provider (play time)."""
        raise NotImplementedError

    @property
    def modes(self):
        return ('dub', 'sub', 'auto')


class NoAudio(Audio):
    """tg/agp: the stream carries one audio track — nothing to choose."""

    capable = False

    def prepare(self, provider, value):
        return None


class AxpAudio(Audio):
    """AnimeX: dub / sub / auto, re-resolved against the server list."""

    def prepare(self, provider, value):
        provider.set_audio(value)


class ZoroAudio(Audio):
    """HiAnime: the picked server label carries its own audio (sub vs dub)."""

    def prepare(self, provider, value):
        provider.set_audio(value)
