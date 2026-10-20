"""tp.characters - who's who in each show: cast, roles, voice actors + links.

Data sources (no keys needed, fast, good donghua coverage):
  * AniList GraphQL (already our metadata backend): one query by MAL id ->
    characters with name + native (CJK) name, role, avatar, favourites,
    voice actors, description and a link per character.
  * Bangumi (bgm.tv) as the Chinese booster/fallback: real CN voice actors.

Everything is cached in characters.json keyed by MAL id with a TTL, so the
cast dialog opens INSTANTLY from cache and the network is touched at most
once a month per show. The UI loads the cache on the GUI thread and only
refreshes in a worker thread (never blocks the window).
"""
import json
import os
import time
from typing import List, Optional

ANILIST_GQL = 'https://graphql.anilist.co'
CAST_TTL = 30 * 86400            # refresh the cast at most once a month
CAST_LIMIT = 24

# one compact query: show + its top cast. NOTE (schema-verified): the cast
# lives in `edges` - role + voiceActors (a direct list) on the edge, the
# person (name/native/avatar/bio/link) under `node`.
QUERY = (
    'query($idMal:Int, $search:String){'
    ' Media(idMal:$idMal, search:$search, type:ANIME){'
    '  id idMal title{romaji english native}'
    '  characters(page:1, perPage:%d, sort:[ROLE, RELEVANCE, FAVOURITES_DESC]){'
    '   edges{ role'
    '     voiceActors{ name{full} language image{large} }'
    '     node{ id name{full native} image{large}'
    '           favourites description(asHtml:false) siteUrl } } } } }'
    % CAST_LIMIT)


def _rows_from_anilist(media: dict) -> List[dict]:
    out = []
    for edge in ((media.get('characters') or {}).get('edges') or []):
        n = edge.get('node') or {}
        va = ((edge.get('voiceActors') or [None])[0]) or {}
        out.append({
            'name': ((n.get('name') or {}).get('full') or '').strip(),
            'native': ((n.get('name') or {}).get('native') or '').strip(),
            'role': (edge.get('role') or '').lower(),
            'image': (n.get('image') or {}).get('large') or '',
            'fav': n.get('favourites') or 0,
            'desc': (n.get('description') or '').strip(),
            'url': n.get('siteUrl') or '',
            'va': ((va.get('name') or {}).get('full') or '').strip(),
            'va_lang': (va.get('language') or '').lower(),
        })
    return out


def _rows_from_bangumi(persons: List[dict]) -> List[dict]:
    """bgm.tv /characters -> our row shape (strong Chinese VA data)."""
    out = []
    for c in persons[:CAST_LIMIT]:
        acts = c.get('actors') or []
        actor = ((acts[0].get('name') if acts and acts[0] else '') or '')
        stat = c.get('stat') if isinstance(c.get('stat'), dict) else {}
        images = c.get('images') if isinstance(c.get('images'), dict) else {}
        out.append({
            'name': (c.get('name') or '').strip(),
            'native': (c.get('name_cn') or c.get('name') or '').strip(),
            'role': 'main' if str(c.get('role')) == '1' else 'supporting',
            'image': images.get('common') or images.get('grid') or '',
            'fav': int(stat.get('favorites') or 0),
            'desc': (c.get('short_desc') or c.get('desc') or '').strip(),
            'url': f"https://bgm.tv/character/{c.get('id')}" if c.get('id') else '',
            'va': actor,
            'va_lang': 'Chinese',
        })
    return out


class CharactersService:
    """Fetch + cache the cast of a show (by MAL id, falling back to title)."""

    def __init__(self, cfg, http=None, bangumi=None):
        self.cfg = cfg
        self.http = http
        self.bangumi = bangumi

    # --- cache -----------------------------------------------------------
    def _all(self) -> dict:
        try:
            d = json.load(open(self.cfg.characters))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _put(self, key: str, rec: dict) -> None:
        try:
            all_ = self._all()
            all_[key] = rec
            os.makedirs(os.path.dirname(self.cfg.characters), exist_ok=True)
            json.dump(all_, open(self.cfg.characters, 'w'))
        except Exception:
            pass

    def cached(self, mal_id=None, title=None) -> Optional[dict]:
        """Fresh-enough cached cast, or None (caller may then fetch)."""
        key = f'mal:{mal_id}' if mal_id else f'title:{(title or "").casefold()}'
        rec = self._all().get(key)
        if rec and time.time() - float(rec.get('fetched') or 0) < CAST_TTL:
            return rec
        return None

    # --- network (worker thread only!) ------------------------------------
    def fetch(self, mal_id=None, title=None) -> Optional[dict]:
        """One AniList query (+ Bangumi boost for CN titles). None on failure."""
        rec = self._anilist(mal_id, title)
        if rec is None:
            return None
        if self.bangumi is not None:
            rec['rows'] = self._boost(rec)
        return rec

    def _anilist(self, mal_id, title) -> Optional[dict]:
        import urllib.request
        try:
            body = json.dumps({
                'query': QUERY,
                'variables': {'idMal': mal_id, 'search': title}}).encode()
            req = urllib.request.Request(
                ANILIST_GQL, data=body,
                headers={'Content-Type': 'application/json',
                         'Accept': 'application/json',
                         'User-Agent': 'tgplay/1.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.load(r)
            media = (d.get('data') or {}).get('Media')
            if not media:
                return None
            rec = {'fetched': time.time(),
                   'anilist_id': media.get('id'),
                   'mal': media.get('idMal') or mal_id,
                   'show': ((media.get('title') or {}).get('romaji')
                            or (media.get('title') or {}).get('english')
                            or title or ''),
                   'native_titles': [t for t in (media.get('title') or {}).values()
                                     if t and any('\u4e00' <= c <= '\u9fff'
                                                  for c in str(t))],
                   'rows': _rows_from_anilist(media)}
            key = (f"mal:{rec['mal']}" if rec.get('mal')
                   else f'title:{(title or "").casefold()}')
            self._put(key, rec)
            return rec
        except Exception:
            return None

    def _boost(self, rec: dict) -> List[dict]:
        """Donghua: merge Bangumi characters (native CN names + CN VAs).

        bgm subject names usually omit the '：arc' suffix, so we try each CN
        title AND its stem until one resolves to a subject with characters."""
        import re as _re
        cands = []
        for t in ([rec.get('show', '')] + list(rec.get('native_titles') or [])):
            if t and any('\u4e00' <= c <= '\u9fff' for c in t):
                if t not in cands:
                    cands.append(t)
                stem = _re.split(r'[：:·]', t)[0].strip()
                if stem and stem not in cands:
                    cands.append(stem)
        if not cands or self.bangumi is None:
            return rec['rows']
        cn = []
        try:
            for kw in cands:
                sid = self.bangumi.subject_id(kw)
                if not sid:
                    continue
                persons = self.bangumi.subject_characters(sid) or []
                cn = _rows_from_bangumi(persons)
                if cn:
                    break
            if not cn:
                return rec['rows']
            have = {r['name'].casefold() for r in rec['rows']}
            for r in cn:                          # CN names/VAs as extra rows
                if r['name'] and r['name'].casefold() not in have:
                    rec['rows'].append(r)
                    have.add(r['name'].casefold())
            rec['has_cn'] = True
        except Exception:
            pass
        return rec['rows']
