"""tp.bangumi - Chinese episode titles from Bangumi (bgm.tv).

Bangumi is the Chinese ACG database and often has donghua episode names that
MAL/AniList/Simkl lack. Its public v0 API is keyless. Search matches CJK titles
only, so the caller passes a Chinese title (we get it from Simkl's alt_titles,
e.g. Mushen Ji -> 牧神记).
"""
import difflib
import json
import re
import urllib.request
from typing import Dict, List, Optional, Tuple

API = 'https://api.bgm.tv'
UA = 'tgplay/1 (https://github.com/; tgplay@example.com)'

# Bangumi stores un-named episodes as pure numbering ('第一百六十六集')
# - those are NOT names; keep them out of the merged cache.
_GENERIC_NUM = re.compile(
    r'^\s*第?\s*[0-9一二三四五六七八九十百千零〇两]+\s*[集话話回]?\s*$', re.I)


class Bangumi:
    def __init__(self, http=None, timeout: int = 20):
        self.timeout = timeout
        self._subjects: Dict[str, Optional[int]] = {}

    def _req(self, url, data=None):
        headers = {'User-Agent': UA, 'Accept': 'application/json'}
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def search(self, keyword: str) -> List[Tuple[int, str, str]]:
        d = self._req(f'{API}/v0/search/subjects?limit=10',
                      {'keyword': keyword, 'filter': {'type': [2]}})
        out = []
        for s in (d.get('data') or []):
            if s.get('id'):
                out.append((s['id'], s.get('name') or '', s.get('name_cn') or ''))
        return out

    def seasons(self, keyword: str) -> List[int]:
        """Subject ids whose name/name_cn contains `keyword`, best first.

        The EXACT title (S1) comes first; clips/recap/movies come last so
        they can't hijack the main subject when it exists."""
        hits = [(i, n, cn) for i, n, cn in self.search(keyword)
                if keyword in (n or '') or keyword in (cn or '')]
        # '一念永恒小剧场' style side-entries drop behind the main ones
        _special = re.compile(r'小剧场|上海剧场|合集|剧场版|特别篇|pv|？广播',
                              re.I)
        hits.sort(key=lambda t: (bool(_special.search(t[1])), bool(t[2]),
                                 t[0]))
        if hits:
            return [i for i, _n, _cn in hits]
        sid = self.subject_id(keyword)
        return [sid] if sid else []

    def grouped_episodes(self, keyword: str) -> Dict[int, str]:
        """{global episode number: title} across all seasons of `keyword`.

        The offset advances by each season's SPAN even when a season has no
        curated names — that skip is exactly what mis-aligned later seasons
        before (numbering drifted, names got wrong). Pure-number titles
        (第一百六十六集-style) are dropped too."""
        out: Dict[int, str] = {}
        offset = 0
        for sid in self.seasons(keyword):
            eps = self.episodes(sid)
            if not eps:
                continue
            for n, t in eps.items():
                if t and not _GENERIC_NUM.match(t):
                    out.setdefault(offset + n, t)
            offset += max(eps)
        return out

    def subject_id(self, keyword: str) -> Optional[int]:
        if keyword in self._subjects:
            return self._subjects[keyword]
        sid = None
        try:
            scored = []
            for i, name, cn in self.search(keyword):
                names = [x for x in (name, cn) if x]
                best = max((difflib.SequenceMatcher(None, keyword.casefold(),
                                                    x.casefold()).ratio()
                            for x in names), default=0)
                scored.append((best, i))
            scored.sort(reverse=True)
            if scored and scored[0][0] >= 0.5:
                sid = scored[0][1]
        except Exception:
            sid = None
        self._subjects[keyword] = sid
        return sid

    def subject_characters(self, subject_id: int) -> List[dict]:
        """bgm.tv characters of a subject (CN names + Chinese voice actors)."""
        try:
            d = self._req(f'{API}/v0/subjects/{subject_id}/characters'
                          '&limit=30')
            return d or []
        except Exception:
            return []

    def episodes(self, subject_id: int) -> Dict[int, str]:
        """{episode number: title}; '' when a subject has ep rows but no
        curated names (grouped_episodes still needs the season span)."""
        out: Dict[int, str] = {}
        offset = 0
        while True:
            d = self._req(f'{API}/v0/episodes?subject_id={subject_id}'
                          f'&limit=100&offset={offset}')
            data = d.get('data') or []
            for e in data:
                ep = e.get('ep')
                t = e.get('name_cn') or e.get('name') or ''
                if isinstance(ep, int):
                    out[ep] = str(t or '')
            total = d.get('total') or 0
            offset += len(data)
            if not data or offset >= total:
                break
        return out


def cjk_title(info: dict, fallback: str = '') -> Optional[str]:
    """First CJK title in a Simkl record's alt_titles (e.g. 牧神记)."""
    for a in ((info or {}).get('alt_titles') or []):
        n = a.get('name') or ''
        if re.search(r'[\u4e00-\u9fff\u3040-\u30ff]', n):
            return n
    if fallback and re.search(r'[\u4e00-\u9fff]', fallback):
        return fallback
    return None
