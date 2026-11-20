"""tp.features.quality - the server/rendition menu, one object per source.

The options form used to parse AnimeX's label strings itself (`src == 'axp'`
in the GUI). Now each source's Quality object renders its own menu shape:
(sources, {source: [sizes]}). Sources without a rendition split return plain
labels and an empty size map.
"""
from abc import ABC
from typing import Dict, List, Tuple


class Quality(ABC):
    def menus(self, groups) -> Tuple[List[str], Dict[str, List[str]]]:
        """(quality/server labels, {server: [rendition sizes]}) for the form."""
        return _labels(groups), {}

    def size_pref(self, choice) -> str:
        """A rendition (e.g. '720p') requested inside a quality label ('')."""
        return ''


def _labels(groups) -> List[str]:
    return [str(g['label'] if isinstance(g, dict) else g)
            for g in (groups or [])]


class TgQuality(Quality):
    """Telegram: quality variants parsed from the .mkv file names."""

    def group(self, names):
        """(qualities, {quality: [names]}) from tp.quality's filename parse."""
        from .. import quality as qmod
        return qmod.group(names)


class AgpQuality(Quality):
    """AnimeGate: the site's group labels ARE the qualities."""


class NoQuality(Quality):
    """Zoro: no rendition menu — the quality ladder is left to mpv."""


class AxpQuality(Quality):
    """AnimeX: labels look like 'nero  (dub+sub)  ·  1080p'; split them so
    the user can pick the server and the rendition independently."""

    def menus(self, groups) -> Tuple[List[str], Dict[str, List[str]]]:
        import re
        size_map: Dict[str, List[str]] = {}
        for g in (groups or []):
            lab = str(g.get('label') if isinstance(g, dict) else g)
            src = lab.split()[0] if lab.split() else lab
            quals: List[str] = []
            if isinstance(g, dict) and g.get('qualities'):
                quals = [str(q) for q in g['qualities'] if q]
            elif '·' in lab:
                q = lab.split('·', 1)[-1].strip()
                if re.match(r'^(\d{3,4}p|~\d+Mbps)$', q):
                    quals = [q]
            size_map.setdefault(src, [])
            for q in quals:
                if q not in size_map[src]:
                    size_map[src].append(q)
        return list(size_map), size_map

    def size_pref(self, choice) -> str:
        import re
        m = re.search(r'(\d{3,4}p)', str(choice or ''), re.I)
        return m.group(1).lower() if m else ''
