"""tp.characters - who's who in each show: cast, roles, voice actors + links.

Sources (no keys, fast, deep coverage):
  * AnimeX/AniList GraphQL by the MAL id: the ANIME's full cast, PAGINATED
    (all pages up to a cap - not just the first 24).
  * The show's OTHER media (manga / light novel / novel relations): their
    casts are fetched too and merged in, tagged with where they come from.
    This is what gives novel-based donghua (Renegade Immortal, A Record of
    a Mortal's Journey, ...) their full cast: the anime entry often lists
    a handful, the novel entry lists dozens/hundreds.
  * Bangumi (bgm.tv) as the Chinese booster: native CN names + CN voice
    actors, merged only for genuinely-missing characters.

Everything is cached in characters.json keyed by MAL id with a TTL, so the
cast dialog opens INSTANTLY from cache; the network is touched at most
once a month per show and always on a worker thread (never blocks the UI).
"""
import json
import os
import time
from typing import List, Optional

ANILIST_GQL = 'https://graphql.anilist.co'
CAST_TTL = 30 * 86400            # refresh the cast at most once a month
CAST_PAGE = 50                   # AniList max per page for characters
CAST_MAX = 300                   # cap for the anime's own cast
SOURCE_MAX = 400                 # cap for all merged source-material rows
SOURCE_MEDIA = 3                 # how many manga/novel relatives to pull

# Cast of one media (or one page of it). No `type:ANIME` on purpose: the
# same query is used for the manga/novel relations (by id).
CAST_QUERY = (
    'query($id:Int, $idMal:Int, $search:String, $page:Int, $perPage:Int){'
    ' Media(id:$id, idMal:$idMal, search:$search){'
    '  id idMal type format'
    '  title{romaji english native}'
    '  characters(page:$page, perPage:$perPage,'
    '             sort:[ROLE, RELEVANCE, FAVOURITES_DESC]){'
    '   pageInfo{ hasNextPage }'
    '   edges{ role'
    '     voiceActors{ name{full} language }'
    '     node{ id name{full native} image{large} favourites'
    '           description(asHtml:false) siteUrl } } } } }')

RELATIONS_QUERY = (
    'query($idMal:Int){ Media(idMal:$idMal){ id'
    ' relations{ edges{ node{ id type format title{romaji english native} } }'
    ' } } }')

SEARCH_SOURCE_QUERY = (
    'query($search:String){ Page(perPage:6){'
    ' media(search:$search, type:MANGA){ id type format'
    '  title{romaji english native} } } }')


def _title_score(a: str, b: str) -> float:
    """Similarity that survives 'Xian Ni' vs 'Renegade Immortal' being the
    same novel under different language titles — token containment wins."""
    import difflib as _dl
    a = ' '.join(str(a or '').casefold().split())
    b = ' '.join(str(b or '').casefold().split())
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    r = _dl.SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        r = max(r, 0.86)
    ta, tb = a.split(), b.split()
    if len(ta) >= 2 and len(tb) >= 2:
        shared = len(set(ta) & set(tb))
        if shared >= 2:
            r = max(r, 0.55 + 0.4 * shared / min(len(ta), len(tb)))
    return r


def _norm_format(fmt: Optional[str]) -> str:
    f = (fmt or '').upper()
    if f in ('NOVEL', 'LIGHT_NOVEL'):
        return 'novel'
    if f in ('MANGA', 'ONE_SHOT', 'MANHWA', 'MANHUA'):
        return 'manga'
    return 'anime'


def _rows_from_media(media: dict, origin: str = 'anime') -> List[dict]:
    """One page of a media's cast -> our row shape."""
    out = []
    for edge in ((media.get('characters') or {}).get('edges') or []):
        n = edge.get('node') or {}
        va = ((edge.get('voiceActors') or [None])[0]) or {}
        out.append({
            'cid': n.get('id'),
            'name': ((n.get('name') or {}).get('full') or '').strip(),
            'native': ((n.get('name') or {}).get('native') or '').strip(),
            'role': (edge.get('role') or '').lower(),
            'image': (n.get('image') or {}).get('large') or '',
            'fav': n.get('favourites') or 0,
            'desc': (n.get('description') or '').strip(),
            'url': n.get('siteUrl') or '',
            'va': ((va.get('name') or {}).get('full') or '').strip(),
            'va_lang': (va.get('language') or '').lower(),
            'from': origin,
        })
    return out


def _rows_from_bangumi(persons: List[dict]) -> List[dict]:
    """bgm.tv /characters -> our row shape (strong Chinese VA data)."""
    out = []
    for c in persons[:200]:
        acts = c.get('actors') or []
        actor = ((acts[0].get('name') if acts and acts[0] else '') or '')
        stat = c.get('stat') if isinstance(c.get('stat'), dict) else {}
        images = c.get('images') if isinstance(c.get('images'), dict) else {}
        out.append({
            'cid': f'bgm:{c.get("id")}',
            'name': (c.get('name') or '').strip(),
            'native': (c.get('name_cn') or c.get('name') or '').strip(),
            'role': 'main' if str(c.get('role')) == '1' else 'supporting',
            'image': images.get('common') or images.get('grid') or '',
            'fav': int(stat.get('favorites') or 0),
            'desc': (c.get('short_desc') or c.get('desc') or '').strip(),
            'url': (f'https://bgm.tv/character/{c.get("id")}'
                    if c.get('id') else ''),
            'va': actor,
            'va_lang': 'Chinese',
            'from': 'bangumi',
        })
    return out


class CharactersService:
    """Fetch + cache the full cast of a show (by MAL id or title)."""

    def __init__(self, cfg, http=None, bangumi=None, fandom=None):
        self.cfg = cfg
        self.http = http
        self.bangumi = bangumi
        self.fandom = fandom

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
        """Anime cast (ALL pages) + manga/novel relatives + Bangumi + wiki."""
        rec = self._anilist(mal_id, title)
        if rec is None:
            return None
        if self.bangumi is not None:
            rec['rows'] = self._boost(rec)
        rec['rows'] = self._merge_wiki(rec)
        return rec

    def _merge_wiki(self, rec: dict) -> List[dict]:
        """Fandom wiki roster: the full cast for novels/donghua whose AniList
        entry is thin. Enough rows already? Skip the extra requests."""
        if len(rec['rows']) >= 120:
            return rec['rows']
        try:
            from .fandom import FandomCharacters
            fandom = self.fandom or FandomCharacters()
            titles = [rec.get('show') or '']
            titles += list(rec.get('native_titles') or [])
            rows = fandom.fetch(titles) or []
        except Exception:
            rows = []
        if not rows:
            return rec['rows']
        have = {r['name'].casefold() for r in rec['rows']}
        added = 0
        for r in rows:
            n = (r.get('name') or '').casefold()
            if n and n not in have:
                rec['rows'].append(r)
                have.add(n)
                added += 1
        if added:
            rec['has_wiki'] = True
            rec['wiki'] = rows[0].get('wiki') or ''
        return rec['rows']

    def _gql(self, query: str, variables: dict) -> Optional[dict]:
        """One GraphQL POST (overridable in tests)."""
        import urllib.request
        try:
            body = json.dumps({'query': query,
                               'variables': variables}).encode()
            req = urllib.request.Request(
                ANILIST_GQL, data=body,
                headers={'Content-Type': 'application/json',
                         'Accept': 'application/json',
                         'User-Agent': 'tgplay/1.0'})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
            return (d.get('data') or {}) or None
        except Exception:
            return None

    def _cast_pages(self, ref: dict, origin: str,
                    limit: int) -> List[dict]:
        """Every character page of one media (up to `limit` rows)."""
        rows: List[dict] = []
        page = 1
        while len(rows) < limit and page <= 12:
            data = self._gql(CAST_QUERY, {**ref, 'page': page,
                                          'perPage': CAST_PAGE})
            media = (data or {}).get('Media')
            if not media:
                break
            got = _rows_from_media(media, origin)
            rows.extend(got)
            nxt = (((media.get('characters') or {}).get('pageInfo') or {})
                   .get('hasNextPage'))
            if not got or not nxt:
                break
            page += 1
        return rows[:limit]

    def _sources(self, mal_id, titles: List[str]) -> List[dict]:
        """The manga / light-novel relatives of this anime (id + origin).

        First the explicit relations; for many donghua the anime entry does
        NOT link its novel, so we ALSO search AniList's manga/novel entries
        by the show's own title(s) and keep close title matches."""
        out: List[dict] = []
        seen = set()

        def add(node):
            if not node or (node.get('type') or '').upper() == 'ANIME':
                return
            origin = _norm_format(node.get('format'))
            if origin == 'anime':
                return
            try:
                nid = int(node['id'])
            except (KeyError, TypeError, ValueError):
                return
            if nid in seen:
                return
            seen.add(nid)
            t = node.get('title') or {}
            out.append({'id': nid, 'origin': origin,
                        'title': t.get('romaji') or t.get('english') or ''})

        data = self._gql(RELATIONS_QUERY, {'idMal': mal_id})
        media = (data or {}).get('Media') or {}
        for edge in (((media.get('relations') or {}).get('edges')) or []):
            add(edge.get('node'))
        if len(out) < SOURCE_MEDIA:
            # title search: the novel often isn't linked, but shares a name
            q = next((t for t in (titles or []) if t), '')
            if q:
                d = self._gql(SEARCH_SOURCE_QUERY, {'search': q})
                cands = (((d or {}).get('Page') or {}).get('media')) or []
                scored = []
                for n in cands:
                    names = [x for x in (n.get('title') or {}).values() if x]
                    best = max((_title_score(q, x) for x in names), default=0)
                    scored.append((best, n))
                for best, n in sorted(scored, key=lambda z: -z[0]):
                    if best >= 0.6:
                        add(n)
                    if len(out) >= SOURCE_MEDIA:
                        break
        return out[:SOURCE_MEDIA]

    def _anilist(self, mal_id, title) -> Optional[dict]:
        ref = {'idMal': mal_id} if mal_id else {'search': title}
        data = self._gql(CAST_QUERY, {**ref, 'page': 1,
                                      'perPage': CAST_PAGE})
        media = (data or {}).get('Media')
        if not media:
            return None
        titles = media.get('title') or {}
        # the anime's own cast, ALL pages
        rows = []
        page = 1
        while len(rows) < CAST_MAX and page <= 8:
            d = self._gql(CAST_QUERY, {**ref, 'page': page,
                                       'perPage': CAST_PAGE})
            m = (d or {}).get('Media')
            if not m:
                break
            got = _rows_from_media(m, 'anime')
            rows.extend(got)
            if not got or not (((m.get('characters') or {}).get(
                    'pageInfo') or {}).get('hasNextPage')):
                break
            page += 1
        rows = rows[:CAST_MAX]
        # manga / novel relatives: their casts often dwarf the anime's
        for src in self._sources(media.get('idMal'),
                                 [titles.get('romaji'),
                                  titles.get('english'),
                                  titles.get('native')]):
            rows += self._cast_pages({'id': src['id']}, src['origin'],
                                     SOURCE_MAX)
            if len(rows) >= SOURCE_MAX:
                break
        rows = self._dedupe(rows)
        rec = {'fetched': time.time(),
               'anilist_id': media.get('id'),
               'mal': media.get('idMal') or mal_id,
               'show': (titles.get('romaji') or titles.get('english')
                        or title or ''),
               'native_titles': [t for t in titles.values()
                                 if t and any('\u4e00' <= c <= '\u9fff'
                                              for c in str(t))],
               'rows': rows}
        key = (f"mal:{rec['mal']}" if rec.get('mal')
               else f'title:{(title or "").casefold()}')
        self._put(key, rec)
        return rec

    @staticmethod
    def _dedupe(rows: List[dict]) -> List[dict]:
        """One row per character id; the anime's row wins (it has the VA)."""
        out, seen = [], set()
        for r in rows:
            k = r.get('cid') or (r.get('name') or '').casefold()
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    # --- bangumi boost (Chinese names + CN voice actors) -----------------
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
