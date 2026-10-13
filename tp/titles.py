"""tp.titles - instant, cache-only episode-title lookups.

Titles are filled once, by `Metadata.refresh_titles()`, when the playlist is
built (see cli). This class only READS the persistent cache, so building the
menu never waits on a metadata API and nothing is searched during playback.
"""
import json
import re
from typing import Dict, Optional

from .translate import has_cjk

_GENERIC = re.compile(
    r'^\s*(episode\s*\d+|ep\s*\d+|第?\s*\d+\s*[集话話話])[\s.:。-]*$', re.I)


def _generic(t: str) -> bool:
    return bool(_GENERIC.match(t or ''))


_RELEASE_PREFIX = re.compile(
    r'^\s*(?:release|已播出?放送)\s*[:：]?\s*'
    r'\d{4}[-/]\d{2}[-/]\d{2}'
    r'(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?'
    r'(?:\s*(?:GMT|UTC)\S*)?'
    r'\s*[-–—]?\s*', re.I)
# Bangumi writes unaired episodes as "Release: 2026/09/03 15:00 GMT - name";
# the real name follows the dash (and sometimes a date is ALL it has).
_RELEASE_ALL = re.compile(r'^\s*(?:release|放送)\s*[:：]?\s*'
                          r'\d{4}[-/]\d{2}[-/]\d{2}(?:\s*[^\W\d_]{2,4})?'
                          r'(?:\s+\d{1,2}:\d{2})?(?:\s*(?:GMT|UTC)\S*)?\s*$',
                          re.I)


def clean_ep_name(t) -> str:
    """Strip the 'Release: date - ' prefix (and date-only names) from
    episode titles; empty string when nothing is left."""
    t = str(t or '').strip()
    t = _RELEASE_PREFIX.sub('', t)
    if _RELEASE_ALL.match(t):
        return ''
    return t.strip()


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
        for key in (f'bgm:{series}', f'simkl:{series}', str(series)):
            t = clean_ep_name(c.get(key, {}).get(str(num)))
            if t and t != '?' and not _generic(t):
                en = self._trans().get(t, t) if has_cjk(t) else t
                return clean_ep_name(en) if en and not _generic(en) else None
        return None

    def cache_count(self, series) -> int:
        """How many numbered episode names the cache holds for `series`
        (any key). 0 when nothing usable is stored."""
        c = self._cache()
        best = 0
        for key in (f'bgm:{series}', f'simkl:{series}', str(series)):
            rows = c.get(key) or {}
            n = sum(1 for k, v in rows.items()
                    if k.isdigit() and clean_ep_name(v)
                    and not _generic(clean_ep_name(v)))
            best = max(best, n)
        return best

    def labels(self, series, eps: Dict[int, str]) -> Dict[int, str]:
        """Cached titles now (instant); generic 'Episode N' is ignored so the
        caller's fallback shows instead; Chinese is translated when cached.

        `series` must be a resolved identifier (the MAL id) — id-pinning
        upstream decides WHICH series these names belong to. Bangumi
        (Chinese + translator) is read first, then Simkl, then the legacy
        key, so old junk rows can't shadow the better data."""
        out = dict(eps)
        if series is None:
            return out
        c = self._cache()
        tr = self._trans()
        for n in eps:
            t = None
            for key in (f'bgm:{series}', f'simkl:{series}', str(series)):
                t = clean_ep_name(c.get(key, {}).get(str(n)))
                if t and not _generic(t):
                    break
            if not t or t == '?' or _generic(t):
                continue
            en = clean_ep_name(tr.get(t, t) if has_cjk(t) else t)
            if en and not _generic(en):
                out[n] = en
        return out
