"""tp.providers.telegram - telethon messages as byte sources.

Telethon is imported lazily, so importing the package never requires it. The
client's asyncio loop runs on a background thread and every call marshals onto
it with `run_coroutine_threadsafe`, which lets the HTTP proxy read bytes from
handler threads. `fetch_exact` stays telethon-agnostic so it is unit-testable.
"""
import asyncio
import os
import threading
from typing import Dict, List, Optional, Tuple

from ..sources import MediaSource
from .base import Provider

API_ID = 2040
API_HASH = 'API_HASH_NOW_IN_ENV'


def default_session() -> str:
    return (os.environ.get('TG_SESSION')
            or os.path.join(os.path.expanduser('~'), '.config', 'tgp',
                            'tg.session'))


def login(session: Optional[str] = None, api_id: int = API_ID,
          api_hash: str = API_HASH):
    """One-time Telegram login (real phone account). Prompts for phone/code."""
    from telethon import TelegramClient
    session = session or default_session()
    os.makedirs(os.path.dirname(session), exist_ok=True)
    with TelegramClient(session, api_id, api_hash) as c:
        me = c.loop.run_until_complete(c.get_me())
    return me


async def fetch_exact(client, msg, offset: int, length: int,
                      attempts: int = 5) -> Optional[bytes]:
    """Exactly `length` bytes at `offset` (Telegram needs 4k alignment; short
    reads looped, transient errors retried, FloodWait's `.seconds` honoured)."""
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
            except Exception as e:
                await asyncio.sleep(getattr(e, 'seconds', 1) + 1)
        else:
            return None if not data else bytes(data[trim:][:length])
    return bytes(data[trim:trim + length])


class TelegramSource(MediaSource):
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


class _TelegramBase:
    """Shared client/loop lifecycle."""

    def _init_client(self, session):
        from telethon import TelegramClient  # lazy
        self.session = session or default_session()
        self.client = TelegramClient(self.session, API_ID, API_HASH)
        self.loop = self.client.loop
        self._loop_started = False

    def run_loop(self):
        if not self._loop_started:
            threading.Thread(target=self.loop.run_forever, daemon=True).start()
            self._loop_started = True

    def _await(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    async def _connect(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError('telegram not logged in (run: tgplay login)')


class TelegramProvider(_TelegramBase, Provider):
    def __init__(self, chat, session=None, window: int = 50, matcher=None):
        self.chat = chat
        self.title = chat
        self.window = window
        self.matcher = matcher
        self._items: List[Tuple[object, str, int]] = []
        self._loaded = False
        self._init_client(session)

    async def _pick(self):
        out = []
        async for msg in self.client.iter_messages(self.chat,
                                                    limit=self.window * 3):
            doc = getattr(msg, 'document', None)
            if doc is None:
                continue
            name = _doc_name(doc)
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
        self.run_loop()
        self._items = self._await(self._load_async())
        self._loaded = True
        return self

    async def _load_async(self):
        await self._connect()
        return await self._pick()

    def episodes(self) -> Dict[int, str]:
        if not self._loaded:
            self.load()
        return {i + 1: name for i, (_m, name, _s) in enumerate(self._items)}

    def display_name(self, num: int):
        if not self._loaded:
            self.load()
        return self._items[num - 1][1]

    def stream(self, num: int) -> TelegramSource:
        if not self._loaded:
            self.load()
        msg, _name, size = self._items[num - 1]
        return TelegramSource(self.client, self.loop, msg, size)


class SingleFileProvider(_TelegramBase, Provider):
    """One Telegram message (the `tg <link>` case), exposed as one episode."""

    def __init__(self, chat, msg_id, session=None):
        self.chat = chat
        self.msg_id = int(msg_id)
        self.title = f'{chat}/{msg_id}'
        self._msg = None
        self._name = ''
        self._size = 0
        self._loaded = False
        self._init_client(session)

    async def _load_async(self):
        await self._connect()
        return await self.client.get_messages(self.chat, ids=self.msg_id)

    def load(self):
        self.run_loop()
        msg = self._await(self._load_async())
        if msg is None or not getattr(msg, 'media', None):
            raise RuntimeError('no media found for that message')
        doc = getattr(msg, 'document', None)
        self._name = _doc_name(doc) if doc else ''
        self._size = doc.size if doc else 0
        if not self._size:
            raise RuntimeError('not a streamable file')
        self._msg = msg
        self._loaded = True
        return self

    def episodes(self) -> Dict[int, str]:
        if not self._loaded:
            self.load()
        return {1: self._name or f'{self.msg_id}.mkv'}

    def display_name(self, num: int):
        return self._name or None

    def stream(self, num: int) -> TelegramSource:
        if not self._loaded:
            self.load()
        return TelegramSource(self.client, self.loop, self._msg, self._size)


def _doc_name(doc) -> str:
    for a in getattr(doc, 'attributes', []):
        if getattr(a, 'file_name', None):
            return a.file_name
    return ''
