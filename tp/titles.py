"""tp.titles - non-blocking episode-title cache.

Titles are cosmetic, so the menu reads this cache **instantly** and never waits
on a metadata API. Missing titles are filled by a background thread that
respects `Metadata`'s per-source circuit breakers, so a dead Jikan/AniList/
Simkl never slows or blocks playback - you just see the plain episode label
until the cache is warm.
"""
import json
import threading
from typing import Dict, Iterable, Optional


class TitleService:
    def __init__(self, metadata, cfg):
        self.meta = metadata
        self.cfg = cfg

    def _cache(self) -> dict:
        try:
            return json.load(open(self.cfg.ep_titles))
        except Exception:
            return {}

    def get(self, series, num: int) -> Optional[str]:
        c = self._cache()
        for key in (f'simkl:{series}', str(series)):
            t = c.get(key, {}).get(str(num))
            if t and t != '?':
                return t
        return None

    def labels(self, series, eps: Dict[int, str]) -> Dict[int, str]:
        """Cached titles now (instant); the site label otherwise."""
        out = dict(eps)
        if series is None:
            return out
        c = self._cache()
        for n in eps:
            t = (c.get(f'simkl:{series}', {}).get(str(n))
                 or c.get(str(series), {}).get(str(n)))
            if t and t != '?':
                out[n] = t
        return out

    def start(self, title: str, nums: Iterable[int],
              upto: Optional[int] = None, anilist_id=None):
        """Fill missing titles in a background daemon thread."""
        todo = [n for n in sorted(nums) if upto is None or n <= upto]
        if not todo:
            return None
        th = threading.Thread(target=self._fill,
                              args=(title, todo, anilist_id), daemon=True)
        th.start()
        return th

    def _fill(self, title, todo, anilist_id):
        mal = self.meta.cached_mal(title)
        if mal is None:
            if self.meta.down('anilist'):
                return
            try:
                mal = self.meta.resolve_mal(title, ask=False)
            except Exception:
                mal = None
        if not mal:
            return
        for n in todo:
            if self.get(mal, n):
                continue
            if self.meta.down('jikan') and (
                    self.meta.simkl is None or self.meta.down('simkl')):
                return  # every title source is cooling down
            try:
                self.meta.ep_title(mal, n, title=title, anilist_id=anilist_id)
            except Exception:
                pass
