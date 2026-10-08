"""tp.providers - turn an identifier into a catalog + byte sources.

A `Provider` knows how to list episodes and produce a fresh `MediaSource` for
any one of them. `AnimeGateProvider` (signed CDN links) and `TelegramProvider`
(telethon messages) implement it, so the proxy and playlist stay backend-
agnostic - the whole point of Phase 3.
"""
from .base import Provider  # noqa: F401
