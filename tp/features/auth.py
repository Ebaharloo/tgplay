"""tp.features.auth - cookies / headers / referer knowledge, per source.

Each source owns its own auth: the player's default referer, the media-host
header cache, and the session-dead detection the GUI asks for. Consumers ask
`provider.auth.default_referer()` / `Auth.dead(...)` - no src literals.
"""
import re
from abc import ABC
from typing import Dict, Optional, Tuple


class Auth(ABC):
    # keyword a failed load of this source carries (its own site name); the
    # GUI scans the registry with dead() instead of keeping marker regexes
    match: Optional[str] = None
    MARKERS: Optional[str] = None
    label = ''

    def default_referer(self) -> Optional[str]:
        """The referer the player uses when the stream carries none."""
        raise NotImplementedError

    @classmethod
    def dead(cls, src: str, target: str, ex) -> Optional[str]:
        """A reason string when a load failed ONLY because this source's
        auth is dead (else None)."""
        if cls.match and cls.match not in f'{src} {target}'.lower():
            return None
        m = str(ex)
        return m if cls.MARKERS and re.search(cls.MARKERS, m, re.I) else None


class AgpAuth(Auth):
    """AnimeGate: Firefox cookie login. Cookies + health live in the
    provider module's GateAuth (they read its cookie db + page parser)."""
    match = 'animegate'
    label = 'AnimeGate'
    MARKERS = (r'logged out|cookie expired|no csrf token|'
               r'no links \(logged|no firefox cookies|'
               r'HTTP Error (401|403)')

    def default_referer(self):
        from ..providers.animegate import BASE
        return BASE + '/'

    def health(self) -> Tuple[bool, str]:
        from ..providers.animegate import GateAuth
        return GateAuth().alive()

    def open_login(self) -> None:
        from ..providers.animegate import GateAuth
        GateAuth().open_login()


class AxpAuth(Auth):
    """AnimeX: per-host media-header cache (which Referer actually serves
    the playlist for this host). Probed once per host per process."""
    label = 'AnimeX'
    _HDRS: Dict[str, dict] = {}

    def default_referer(self):
        from ..providers.animex import MEDIA_REFERER
        return MEDIA_REFERER

    def headers_for(self, url: str, http=None) -> dict:
        from ..providers.animex import DEFAULT_UA, SITE, _quiet_close
        host = re.sub(r'^[a-z]+://([^/]+).*$', r'\1', url or '')
        if host in self._HDRS:
            return self._HDRS[host]
        own = f'https://{host}/'
        for hd in ({'Referer': self.default_referer(), 'User-Agent': DEFAULT_UA},
                   {'Referer': SITE + '/', 'User-Agent': DEFAULT_UA},
                   {'Referer': own, 'User-Agent': DEFAULT_UA},
                   {'User-Agent': DEFAULT_UA}):
            try:
                r = http.open(http.request(url, headers=dict(
                    hd, Accept='*/*', Range='bytes=0-1023')))
                try:
                    ok = b'#EXTM3U' in r.read(16)
                finally:
                    _quiet_close(r)
                if ok:
                    self._HDRS[host] = hd
                    return hd
            except Exception:
                continue
        return {'Referer': self.default_referer(), 'User-Agent': DEFAULT_UA}


class ZoroAuth(Auth):
    """HiAnime: each stream carries its own embed-origin Referer; the
    mirror pick lives in the provider's `base` property."""
    label = 'HiAnime'

    def default_referer(self):
        return None


class TgAuth(Auth):
    """Telegram: Telethon session, no HTTP - nothing to send to the player."""
    label = 'Telegram'

    def default_referer(self):
        return None
