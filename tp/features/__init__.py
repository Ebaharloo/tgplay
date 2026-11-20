"""tp.features - the per-source feature objects and the REGISTRY.

One feature class per capability, one subclass per source: a source owns its
own objects, so a bug fixed in one source's object can never break another.
`REGISTRY` (plus `get`) is the ONE table allowed to name sources; consumers
ask for a feature through the provider (`provider.audio`, `provider.quality`)
and never branch on a src literal.
"""
from .audio import Audio, AxpAudio, NoAudio, ZoroAudio
from .servers import (AgpServers, AxpServers, Servers, TgServers,
                      ZoroServers)
from .quality import (AgpQuality, AxpQuality, NoQuality, Quality, TgQuality)

REGISTRY = {
    'audio': {'axp': AxpAudio, 'zoro': ZoroAudio},
    'quality': {'tg': TgQuality, 'tgp': TgQuality, 'agp': AgpQuality,
                'axp': AxpQuality},
    'servers': {'tg': TgServers, 'tgp': TgServers, 'agp': AgpServers,
                'axp': AxpServers, 'zoro': ZoroServers},
}


def get(src: str, feature: str):
    """The feature class for (src, feature); None when the source lacks it."""
    return REGISTRY.get(feature, {}).get(src)
