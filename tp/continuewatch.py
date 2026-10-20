"""tp.continuewatch - the "Continue watching" shelf.

Builds the in-progress rail from the Simkl library rows the sidebar already
fetches (`library.overview()['rem']`):

    * only STARTED, unfinished shows (0 < watched, next_ep < total),
    * de-duplicated by title (Simkl sometimes has split entries),
    * newest activity first (`last_watched`, then air date),
    * a poster per show: Simkl's own poster (`simkl.in/posters/<path>_m.webp`)
      or an AniList cover by MAL id (batched + cached in posters.json).

Pure data (no Qt), so it's fully unit-testable; the window only draws it.
"""
import json
import os
import time
from typing import Dict, List

SIMKL_POSTER = 'https://simkl.in/posters/{path}_m.webp'
ANILIST_GQL = 'https://graphql.anilist.co'
COVERS_TTL = 30 * 86400
COVER_QUERY = ('query($ids:[Int]){ Page(perPage:50){ media(idMal_in:$ids, '
               'type:ANIME){ idMal coverImage{large} } } }')


class CoverArt:
    """AniList cover images for shows Simkl has no poster for (cached)."""

    def __init__(self, cfg, http=None):
        self.cfg = cfg
        self.http = http

    def _all(self) -> dict:
        try:
            d = json.load(open(self.cfg.posters))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def covers(self, mal_ids: List[int]) -> Dict[int, str]:
        cache = self._all()
        now = time.time()
        want = []
        for m in mal_ids:
            rec = cache.get(str(m)) or {}
            if rec.get('url') and now - float(rec.get('fetched') or 0) < COVERS_TTL:
                continue
            want.append(int(m))
        if want:
            got = self._fetch(want)
            for m, url in got.items():
                if url:
                    cache[str(m)] = {'url': url, 'fetched': now}
            if got:
                try:
                    os.makedirs(os.path.dirname(self.cfg.posters), exist_ok=True)
                    json.dump(cache, open(self.cfg.posters, 'w'))
                except Exception:
                    pass
        out = {}
        for m in mal_ids:
            u = (cache.get(str(m)) or {}).get('url')
            if u:
                out[int(m)] = u
        return out

    def _fetch(self, mal_ids: List[int]) -> Dict[int, str]:
        import urllib.request
        try:
            body = json.dumps({'query': COVER_QUERY,
                               'variables': {'ids': mal_ids}}).encode()
            req = urllib.request.Request(
                ANILIST_GQL, data=body,
                headers={'Content-Type': 'application/json',
                         'Accept': 'application/json',
                         'User-Agent': 'tgplay/1.0'})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
            media = ((((d.get('data') or {}).get('Page') or {})
                      .get('media')) or [])
            out = {}
            for m in media:
                if m.get('idMal') and (m.get('coverImage') or {}).get('large'):
                    out[int(m['idMal'])] = m['coverImage']['large']
            return out
        except Exception:
            return {}


class ContinueWatching:
    """In-progress shows for the shelf (poster, progress, next episode)."""

    def __init__(self, cfg, http=None, art: CoverArt = None):
        self.cfg = cfg
        self.http = http
        self.art = art or (CoverArt(cfg, http) if cfg is not None else None)

    @staticmethod
    def _dedupe(rows: List[dict]) -> List[dict]:
        out, seen = [], set()
        for r in rows:
            t = (r.get('title') or '').casefold()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(r)
        return out

    def items(self, rem: List[dict], limit: int = 10) -> List[dict]:
        rows = []
        for r in rem or []:
            try:
                nxt = int(r.get('next_ep') or 0)
                watched = int(r.get('watched') or 0)
                total = int(r.get('total') or 0)
            except (TypeError, ValueError):
                continue
            if not r.get('title') or nxt <= 1 and watched <= 0:
                continue                       # never started
            if total and nxt > total:
                continue                       # finished
            rows.append(dict(r, next_ep=nxt, watched=watched, total=total))
        rows.sort(key=lambda r: str(r.get('last_watched') or r.get('air_date')
                                    or ''), reverse=True)
        rows = self._dedupe(rows)[:limit]

        # posters: Simkl path first; AniList cover for the rest (batched)
        need_mal = [int(r['mal']) for r in rows
                    if not r.get('poster') and r.get('mal')]
        covers = {}
        if need_mal and self.art is not None:
            try:
                covers = self.art.covers(need_mal)
            except Exception:
                covers = {}
        out = []
        for r in rows:
            poster = r.get('poster') or ''
            img = (SIMKL_POSTER.format(path=poster) if poster else
                   covers.get(int(r['mal']), '') if r.get('mal') else '')
            pct = (100.0 * r['watched'] / r['total']) if r.get('total') else 0.0
            out.append({'title': r['title'],
                        'next_ep': r['next_ep'],
                        'watched': r['watched'],
                        'total': r['total'],
                        'pct': max(0.0, min(100.0, pct)),
                        'mal': r.get('mal'),
                        'simkl': r.get('simkl'),
                        'image': img,
                        'last_watched': r.get('last_watched') or ''})
        return out
