"""tp.sources - the bytes behind a stream, behind one interface.

A `MediaSource` is anything with a known size and exact ranged reads. AniGate
(signed CDN over HTTP) and Telegram (telethon) become two implementations, so
the proxy and playlist never special-case a backend.
"""
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional

from .http import HttpClient, _quiet_close


class MediaSource(ABC):
    @property
    @abstractmethod
    def size(self) -> int:
        """Total length in bytes (0 when unknown)."""

    @abstractmethod
    def read(self, lo: int, hi: int) -> bytes:
        """Exact bytes [lo, hi); may be short at EOF."""


class BytesSource(MediaSource):
    """In-memory source (tests, and small fallbacks)."""

    def __init__(self, data: bytes):
        self._data = data

    @property
    def size(self) -> int:
        return len(self._data)

    def read(self, lo: int, hi: int) -> bytes:
        return self._data[lo:hi]


class HttpSource(MediaSource):
    """Ranged HTTP source (animegate / any direct URL + headers)."""

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None,
                 http: Optional[HttpClient] = None, timeout: int = 60):
        self.url = url
        self.headers = dict(headers or {})
        self.http = http or HttpClient(timeout=timeout)
        self._size: Optional[int] = None

    @property
    def size(self) -> int:
        if self._size is None:
            self._size = self._probe()
        return self._size

    def _probe(self) -> int:
        for attempt in range(3):
            try:
                r = self.http.open(self.http.request(
                    self.url, headers={**self.headers, 'Range': 'bytes=0-1'}))
                try:
                    cr = r.headers.get('Content-Range', '')
                    cl = r.headers.get('Content-Length', '0')
                    r.read(2)  # drain before close (py3.14 finalizer)
                finally:
                    _quiet_close(r)
                return int(cr.rsplit('/', 1)[1]) if '/' in cr else int(cl or 0)
            except Exception:
                time.sleep(0.4 * (attempt + 1))   # CDN blip: retry
        return 0

    def read(self, lo: int, hi: int) -> bytes:
        return self.http.range_bytes(self.url, self.headers, lo, hi)


class DirectSource(MediaSource):
    """A source mpv plays itself (HLS/DASH/whatever) - no local proxy.

    Used by providers whose backend hands out segmented/streamed URLs (e.g.
    AnimeX m3u8). `size`/`read` exist only to satisfy the interface; the
    Playlist sees `direct = True` and passes `url` straight to the player with
    its headers (referer) and any external subtitle tracks.
    """

    direct = True

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None,
                 subs: Optional[list] = None):
        self.url = url
        self.headers = dict(headers or {})
        self.subs = list(subs or [])   # [(label, url), ...]

    @property
    def size(self) -> int:
        return 0

    def read(self, lo: int, hi: int) -> bytes:
        raise NotImplementedError('DirectSource is played by mpv, not proxied')

