"""tp.titles - instant, cache-only episode-title lookups.

Titles are filled once, by `Metadata.refresh_titles()`, when the playlist is
built (see cli). This class only READS the persistent cache, so building the
menu never waits on a metadata API and nothing is searched during playback.
"""
import json
from typing import Dict, Optional

from .translate import has_cjk


class TitleService:
    def __init__(self, metadata, cfg):
        self.meta = metadata
        self.cfg = cfg

    def _cache(self) -> dict:
        try:
            return json.load(open(self.cfg.ep_titles))
        except Exception:
            return {}

    def _trans(self) -> dict:
        try:
            return json.load(open(self.cfg.translations))
        except Exception:
            return {}

    def get(self, series, num: int) -> Optional[str]:
        c = self._cache()
        for key in (f'simkl:{series}', str(series)):
            t = c.get(key, {}).get(str(num))
            if t and t != '?':
                return self._english(t)
        return None

    def labels(self, series, eps: Dict[int, str]) -> Dict[int, str]:
        """Cached titles now (instant); translated to English when available."""
        out = dict(eps)
        if series is None:
            return out
        c = self._cache()
        tr = self._trans()
        for n in eps:
            t = (c.get(f'simkl:{series}', {}).get(str(n))
                 or c.get(str(series), {}).get(str(n)))
            if t and t != '?':
                out[n] = tr.get(t, t) if has_cjk(t) else t
        return out

    def _english(self, t: str) -> str:
        return self._trans().get(t, t) if has_cjk(t) else t
