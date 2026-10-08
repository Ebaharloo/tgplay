"""tp.providers.telegram - telethon messages as byte sources.

Telethon is imported lazily (inside classes/functions) so importing this module
- and the whole package - never requires the dependency. `fetch_exact` is
deliberately telethon-agnostic (retries on any error, honours a FloodWait's
`.seconds`) so it can be unit-tested with a fake client.
"""
import asyncio
import os
import threading
from typing import Dict, List, Optional, Tuple

from ..sources import MediaSource
from .base import Provider

API_ID = 2040
API_HASH = 'API_HASH_NOW_IN_ENV'


async def fetch_exact(client, msg, offset: int, length: int,
                      attempts: int = 5) -> Optional[bytes]:
    """Exactly `length` bytes at `offset` (Telegram needs 4k-aligned offsets;
    short reads are looped, transient errors retried)."""
    aligned = (offset // 4096) * 4096
    trim = offset - aligned
    data = bytearray()
    while len(data) < length + trim:
        want = (length + trim) - len(data)
        req = min(1024 * 1024, want)
        pos = aligned + len(data)
        for _ in range(attempts):
            try:
                part = b''
                async for chunk in client.iter_download(
                        msg, offset=pos, request_size=req, chunk_size=req):
                    part += chunk
                    if len(part) >= req:
                        break
                if not part:
                    return None if not data else bytes(data[trim:][:length])
                data += part[:req]
                break
            except Exception as e:  # FloodWait etc: back off and retry
                await asyncio.sleep(getattr(e, 'seconds', 1) + 1)
        else:
            return None if not data else bytes(data[trim:][:length])
    return bytes(data[trim:trim + length])


class TelegramSource(MediaSource):
    """Bytes from one Telegram message, driven on the client's asyncio loop."""

    def __init__(self, client, loop, msg, size: int):
        self.client = client
        self.loop = loop
        self.msg = msg
        self._size = size

    @property
    def size(self) -> int:
        return self._size

    def read(self, lo: int, hi: int) -> bytes:
        if hi <= lo:
            return b''
        fut = asyncio.run_coroutine_threadsafe(
            fetch_exact(self.client, self.msg, lo, hi - lo), self.loop)
        return fut.result() or b''


class TelegramProvider(Provider):
    def __init__(self, chat, session=None, api_id=API_ID, api_hash=API_HASH,
                 window=50, matcher=None):
        from telethon import TelegramClient  # lazy
        self.chat = chat
        self.session = session or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), '.tg_session')
        self.client = TelegramClient(self.session, api_id, api_hash)
        self.loop = self.client.loop
        self.window = window
        self.matcher = matcher
        self.title = chat
        self._items: List[Tuple[object, str, int]] = []
        self._loaded = False

    async def _connect(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError('telegram not logged in (run tgp_login once)')

    async def _pick(self):
        out = []
        async for msg in self.client.iter_messages(self.chat,
                                                    limit=self.window * 3):
            doc = getattr(msg, 'document', None)
            if doc is None:
                continue
            name = ''
            for a in getattr(doc, 'attributes', []):
                if getattr(a, 'file_name', None):
                    name = a.file_name
                    break
            if not name.lower().endswith('.mkv'):
                continue
            if self.matcher and self.matcher.lower() not in name.lower():
                continue
            out.append((msg, name, doc.size))
            if len(out) >= self.window:
                break
        out.reverse()  # oldest of the window first
        return out

    def load(self):
        self.loop.run_until_complete(self._connect())
        self._items = self.loop.run_until_complete(self._pick())
        self._loaded = True
        return self

    def run_loop(self):
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def episodes(self) -> Dict[int, str]:
        if not self._loaded:
            self.load()
        return {i + 1: name for i, (_m, name, _s) in enumerate(self._items)}

    def stream(self, num: int) -> TelegramSource:
        if not self._loaded:
            self.load()
        msg, _name, size = self._items[num - 1]
        return TelegramSource(self.client, self.loop, msg, size)
