"""tp.finder - id-first show finding: the smart side of search.

Everything we KNOW about a show is used to find the EXACT link on each
source and to pin episode names to the right entry:

- Simkl/library entries carry mal / anilist / simkl ids and the Simkl
  record carries EVERY name form (English, romanized, CJK).
- AnimeX search returns `malId`/`anilistId` per hit: a candidate whose id
  equals the known id is provably the right show (ranked first, flagged
  'id' instead of fuzzy 'name').
- AnimeGate carries no ids (its pages are titled in romanized/CJK forms),
  so every name we know is run as its OWN search query and all hits are
  scored against the full name set.
- When a candidate is picked, its MAL id is PINNED to the link
  (`Metadata.remember_link_mal`); `tp.session.open_session` reads the pin
  first, so episode names come from the right MAL entry — never from a
  fuzzy title guess of another season.
"""
import difflib
import re
from typing import Dict, List, Optional

_MAX_NAMES = 4          # how many name forms to run as queries
_MAX_OUT = 12


def _norm(t) -> str:
    return ' '.join(str(t or '').casefold().split()).strip()


def _to_int(v) -> Optional[int]:
    try:
        return int(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


class ShowFinder:
    """Find the right link for a show using every id and name we know."""

    def __init__(self, cfg=None, http=None):
        self.cfg = cfg
        self.http = http
        self._meta = None

    # --- what we know ----------------------------------------------------
    @property
    def meta(self):
        if self._meta is None and self.cfg is not None:
            from .metadata import Metadata
            self._meta = Metadata(self.cfg, self.http)
        return self._meta

    def known(self, title: str = None, entry: Dict = None) -> Dict:
        """Collect ids + every name form for a show.

        `entry` is a library/feed row (may carry mal/anilist/simkl ids);
        plain searches pass just `title`. Alt names from the Simkl record
        are only trusted when the record's own title actually resembles
        what was typed (a bad resolve must not pollute the query set)."""
        e = dict(entry or {})
        k = {'title': _norm(title or e.get('title')),
             'mal': _to_int(e.get('mal')),
             'anilist': _to_int(e.get('anilist')),
             'simkl': _to_int(e.get('simkl')),
             'names': []}                       # INSERTION order: record rank

        def add_name(n):
            n = _norm(n)
            if n and len(n) > 2 and n not in k['names']:
                k['names'].append(n)
        add_name(k['title'])
        rec = self._record(k)
        if rec:
            rec_title = _norm(rec.get('title'))
            alt_names = [(_norm((a or {}).get('name')), a)
                         for a in (rec.get('alt_titles') or [])]
            same = bool(e) or _ratio(k['title'], rec_title) >= 0.5 or any(
                _ratio(k['title'], n) >= 0.5 for n, _a in alt_names)
            if not same:
                return k                       # fuzzy record is NOT this show
            ids = rec.get('ids') or {}
            k['mal'] = k['mal'] or _to_int(ids.get('mal'))
            k['anilist'] = k['anilist'] or _to_int(ids.get('anilist'))
            k['simkl'] = k['simkl'] or _to_int(ids.get('simkl'))
            k['entry_ids'] = bool(e and (e.get('mal') or e.get('simkl')
                                         or e.get('anilist')))
            add_name(rec.get('title'))         # the record's own name first
            for n, _a in alt_names:
                add_name(n)
        return k

    def _record(self, k: Dict) -> Optional[dict]:
        """The Simkl record (ids + alt titles) for what we know.

        A known simkl id is read DIRECTLY (the sidebar rows carry it);
        otherwise resolve by mal/anilist/title."""
        m = self.meta
        try:
            s = m.simkl if m is not None else None
            if s is None or not s.available():
                return None
            if k.get('simkl'):
                sid = k['simkl']
                rec = s._records.get(sid)
                if rec is None:
                    rec = s._get(f'/anime/{sid}')
                    s._records[sid] = rec
                return rec
            return s.info(mal=k.get('mal'), anilist=k.get('anilist'),
                          query=k.get('title') or None)
        except Exception:
            return None

    # --- scoring ----------------------------------------------------------
    @staticmethod
    def _score(cand: Dict, k: Dict) -> float:
        """100+ for an exact id hit; fuzzy name similarity otherwise."""
        if k.get('mal') and _to_int(cand.get('malId')) == k['mal']:
            return 100.0
        if k.get('anilist') and _to_int(cand.get('anilistId')) == k['anilist']:
            return 95.0
        got = _norm(cand.get('title'))
        best = 0.0
        for n in ([k['title']] + list(k.get('names') or [])):
            best = max(best, _ratio(n, got))
        return best

    def find(self, title: str = None, entry: Dict = None,
             sources=('agp', 'axp')) -> List[dict]:
        """Candidates from every source, best match first.

        Each hit keeps its provider ids (malId/anilistId) and gains
        'score' + 'matched' ('id' = provably the same show)."""
        k = self.known(title=title, entry=entry)
        names = [n for n in k['names'] if n][:_MAX_NAMES]
        cands: Dict[str, dict] = {}
        for name in names:
            for src in sources:
                for r in self._search_one(src, name):
                    u = str(r.get('url') or '')
                    if not u:
                        continue
                    c = cands.setdefault(u, dict(r))
                    for key in ('malId', 'anilistId'):
                        if r.get(key) and not c.get(key):
                            c[key] = r[key]
        out = []
        for c in cands.values():
            c['score'] = self._score(c, k)
            c['matched'] = ('id' if c['score'] >= 95 else
                            'name' if c['score'] >= 0.5 else 'maybe')
            # ids we may PIN onto the link: only what the candidate PROVES
            # (its own malId/anilistId) or what the sidebar entry carried -
            # never a fuzzy query-resolve, which could be another season.
            own = k.get('entry_ids')
            ids = {'mal': _to_int(c.get('malId')) or (k.get('mal') if own else None),
                   'anilist': _to_int(c.get('anilistId')) or (k.get('anilist') if own else None),
                   'simkl': k.get('simkl') if own else None}
            c['ids'] = {a: b for a, b in ids.items() if b}
            out.append(c)
        out.sort(key=lambda c: c['score'], reverse=True)
        return out[:_MAX_OUT]

    @staticmethod
    def _search_one(src: str, name: str) -> List[dict]:
        try:
            if src == 'axp':
                from .providers.animex import search as ax
                return ax(name) or []
            from .providers.animegate import search as ag
            return ag(name) or []
        except Exception:
            return []

    # --- pin the id to the link ------------------------------------------
    def pin(self, cand: Dict) -> None:
        """Write the candidate's known MAL id onto its link, so loading it
        later (open_session) paints names from the RIGHT entry immediately."""
        if not cand:
            return
        mal = _to_int((cand.get('ids') or {}).get('mal')) \
            or _to_int(cand.get('malId'))
        url = str(cand.get('url') or '')
        m = self.meta
        if mal and url and m is not None:
            try:
                m.remember_link_mal(url, mal)
            except Exception:
                pass


def _tokens(s: str) -> List[str]:
    return [t for t in re.split(r'\W+', s) if t]


def _ratio(a: str, b: str) -> float:
    """Name similarity that survives TRANSLITERATION spelling differences:
    'Fanren Xiu Xian Zhuan' vs 'Fanren Xiu Xian Zhuang' share a core, even
    though a raw char-ratio is low. Tokens: containment over the smaller
    name's token set, blended with the char ratio."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    best = r
    if a in b or b in a:
        best = max(best, 0.86)
    ta, tb = _tokens(a), _tokens(b)
    if len(ta) >= 2 and len(tb) >= 2:
        shared = len(set(ta) & set(tb))
        if shared >= 2:
            contain = shared / min(len(ta), len(tb))
            best = max(best, 0.55 + 0.4 * contain)
    return best
