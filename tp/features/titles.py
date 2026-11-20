"""tp.features.titles - episode names + MAL pinning, one object per source.

One shared flow replaces the copy-pasted open_session branches: build the
provider's own labels, resolve + pin the MAL entry, paint real names, and
(optionally, per source) fetch the missing ones in the background.
"""
import threading
from abc import ABC
from typing import Dict, Tuple

from ..titles import clean_ep_name


def safe_mal(meta, title):
    """Fuzzy title -> MAL id (never raises). Whether its names may be
    PAINTED onto a page is decided by the paint guard in TitleService."""
    try:
        mal = meta.cached_mal(title)
        if mal is None:
            mal = meta.resolve_mal(title, ask=False)
        return mal
    except Exception:
        return None


class Titles(ABC):
    def open_labels(self, prov, meta, svc, target, *, wait_titles: bool = False
                    ) -> Tuple[Dict[int, str], object]:
        """(labels, pinned mal) for a freshly built provider."""
        base = self.provider_labels(prov)
        mal = self.resolve_mal(prov, meta, target)
        if not mal:
            return base, None
        meta.remember_link_mal(str(target), mal)
        labels = svc.labels(mal, base)
        self.season_guard(meta, svc, mal, base)
        self.refresh_missing(prov, meta, svc, mal, base, wait_titles)
        return svc.labels(mal, base), mal

    # --- per-source hooks ------------------------------------------------
    def provider_labels(self, prov) -> Dict[int, str]:
        return dict(prov.episodes())

    def resolve_mal(self, prov, meta, target):
        return meta.link_mal(str(target)) or safe_mal(meta, prov.title)

    _SEASON_MSG = ('titles: kept clean - MAL lists {cached} episodes but '
                   'this page has {n}; painting would mix seasons')

    def season_guard(self, meta, svc, mal, base) -> None:
        """Never paint when MAL's episode count clearly mismatches the page."""
        missing = [n for n in base if str(base[n]).startswith('Episode ')]
        if missing and len(missing) == len(base):
            cached = svc.cache_count(mal)
            if cached and cached != len(base):
                from .. import log
                log.cprint(self._SEASON_MSG.format(cached=cached,
                                                   n=len(base)))

    def refresh_missing(self, prov, meta, svc, mal, base,
                        wait_titles: bool) -> None:
        """Fetch the episode names MAL is missing (background, optional wait)."""
        missing = [n for n in base if str(base[n]).startswith('Episode ')]
        if not (missing and mal):
            return
        from .. import log
        log.cprint(f'titles: looking up {len(missing)} missing '
                   'episode name(s)...')
        th = threading.Thread(
            target=lambda: meta.refresh_titles(mal, prov.title), daemon=True)
        th.start()
        if wait_titles:              # the terminal menu wants names NOW
            th.join(timeout=5)
            if th.is_alive():
                log.cprint('titles: still fetching names in the '
                           'background (they will show next time)')
        meta._refreshed.add(mal)


class TgTitles(Titles):
    """Telegram: the .mkv file name is the label; no MAL painting."""

    def open_labels(self, prov, meta, svc, target, *, wait_titles=False):
        return dict(prov.episodes()), None


class MalTitles(Titles):
    """Shared MAL painting flow (agp; axp specializes it)."""


class AxpTitles(MalTitles):
    """AnimeX: strips Bangumi's 'Release: date - ' marker BEFORE anything
    reads the labels, and prefers the provider's own exact malId."""

    _SEASON_MSG = ('titles: kept clean - MAL lists {cached} episodes but '
                   'this page has {n}; painting would mix seasons')

    def provider_labels(self, prov):
        return {n: (clean_ep_name(t) or t)
                for n, t in dict(prov.episodes()).items()}

    def resolve_mal(self, prov, meta, target):
        return (getattr(prov, 'mal_id', None) or meta.link_mal(str(target))
                or safe_mal(meta, prov.title))


class ZoroTitles(MalTitles):
    """HiAnime: paint from MAL, but no background fetch today."""

    def provider_labels(self, prov):
        return dict(prov.episodes())

    def season_guard(self, meta, svc, mal, base) -> None:
        return None

    def refresh_missing(self, prov, meta, svc, mal, base,
                        wait_titles) -> None:
        return None
