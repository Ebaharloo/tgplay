"""tp.features - the per-source feature objects and the REGISTRY.

One feature class per capability, one subclass per source: a source owns its
own objects, so a bug fixed in one source's object can never break another.
`REGISTRY` (plus `get`) is the ONE table allowed to name sources; consumers
ask for a feature through the provider (`provider.audio`, `provider.quality`)
and never branch on a src literal.
"""
from .audio import Audio, AxpAudio, NoAudio, ZoroAudio
from .auth import AgpAuth, Auth, AxpAuth, TgAuth, ZoroAuth
from .quality import AgpQuality, AxpQuality, NoQuality, Quality, TgQuality
from .search import AgpSearch, AxpSearch, Search, ZoroSearch
from .servers import (AgpServers, AxpServers, Servers, TgServers,
                      ZoroServers)
from .sizes import AgpSizes, NoSizes, Sizes, TgSizes
from .titles import (AxpTitles, MalTitles, TgTitles, Titles, ZoroTitles)
from .warm import HlsWarm, MirrorWarm, Warm

REGISTRY = {
    'audio': {'axp': AxpAudio, 'zoro': ZoroAudio},
    'auth': {'tg': TgAuth, 'tgp': TgAuth, 'agp': AgpAuth,
             'axp': AxpAuth, 'zoro': ZoroAuth},
    'quality': {'tg': TgQuality, 'tgp': TgQuality, 'agp': AgpQuality,
                'axp': AxpQuality},
    'search': {'agp': AgpSearch, 'axp': AxpSearch, 'zoro': ZoroSearch},
    'servers': {'tg': TgServers, 'tgp': TgServers, 'agp': AgpServers,
                'axp': AxpServers, 'zoro': ZoroServers},
    'sizes': {'tg': TgSizes, 'tgp': TgSizes, 'agp': AgpSizes},
    'titles': {'tg': TgTitles, 'tgp': TgTitles, 'agp': MalTitles,
               'axp': AxpTitles, 'zoro': ZoroTitles},
    'warm': {'tg': MirrorWarm, 'tgp': MirrorWarm, 'agp': MirrorWarm,
             'axp': HlsWarm, 'zoro': HlsWarm},
}


def _tg_provider(target, cfg=None, opts=None, window=None, matcher=None,
                 http=None):
    """Telegram target -> SingleFileProvider (one message) or the channel view."""
    from .providers.telegram import SingleFileProvider, TelegramProvider
    chat, msg_id = _telegram_target(target)
    if msg_id is not None:
        return SingleFileProvider(chat, msg_id, cfg.tg_session)
    return TelegramProvider(chat, session=cfg.tg_session,
                            window=int(window or 50), matcher=matcher)


def _telegram_target(target):
    """('channel', msg_id) for a t.me link / 'channel msgid' (msg_id may be None)."""
    import re
    m = re.search(r't\.me/([A-Za-z0-9_]+)(?:/(\d+))?', target or '')
    if m:
        return m.group(1), (int(m.group(2)) if m.group(2) else None)
    parts = (target or '').split()
    if len(parts) >= 2 and parts[1].isdigit():
        return parts[0].lstrip('@'), int(parts[1])
    return (target or '').lstrip('@'), None


# Provider construction lives here too: the one other place allowed to name
# sources (the src -> provider routing table).
REGISTRY['provider'] = {
    'agp': lambda target, cfg=None, opts=None, window=None, matcher=None,
           http=None: __import__('tp.providers.animegate',
                                 fromlist=['AnimeGateProvider']
                                 ).AnimeGateProvider(
        target, quality=(opts or {}).get('f'), http=http),
    'axp': lambda target, cfg=None, opts=None, window=None, matcher=None,
           http=None: __import__('tp.providers.animex',
                                 fromlist=['AnimeXProvider']).AnimeXProvider(
        target, quality=(opts or {}).get('f'),
        audio=(opts or {}).get('audio') or 'dub', http=http),
    'zoro': lambda target, cfg=None, opts=None, window=None, matcher=None,
            http=None: __import__('tp.providers.zoro',
                                  fromlist=['ZoroProvider']).ZoroProvider(
        target, quality=(opts or {}).get('f'),
        audio=(opts or {}).get('audio') or 'dub', http=http),
    'tg': _tg_provider,
    'tgp': _tg_provider,
}


def get(src: str, feature: str):
    """The feature class for (src, feature); None when the source lacks it."""
    return REGISTRY.get(feature, {}).get(src)
