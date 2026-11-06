"""tp.recent - the "Recently aired" rail (pure data, no Qt).

Same rows `library.overview()` already returns, but a different question:
which shows aired an episode inside the last N days, that he either started
or follows (a new season of something he watched counts even when Simkl shows
0 episodes watched on that season).

    * started-or-followed only (watched/last_watched, or on the list and
      next_ep set), plus new seasons of titles he has watched,
    * one card per show (base title, newest air date wins),
    * newest air date first, then newest episode number,
    * poster: Simkl's own, else an AniList cover (CoverArt cache).

The rail's settings live in ui.json (`window.rails`) - loaded/clamped here so
the dialog and the loader agree on the ranges.
"""
import re
from datetime import date, timedelta
from typing import List

from .config import load_json, save_json
from .continuewatch import CoverArt, SIMKL_POSTER

DAYS = (7, 14, 30)
DEFAULT_RAILS = {
    'continue': {'limit': 10},
    'recent': {'days': 14, 'include_new_seasons': True, 'limit': 20},
    'sidebar': {'show_days': True, 'include_new_seasons': True, 'days': 14},
}

_TAIL = re.compile(
    r'(?:[\s\-–—]*\(\s*\d{4}\s*\)'                      # (1999)
    r'|[\s\-–—]*\b(?:season\s*\d+|\d+(?:st|nd|rd|th)\s+season'
    r'|part\s*\d+|\d+(?:st|nd|rd|th)\s+part|tv)\b'
    r')\s*$', re.I)
_SEP = re.compile(r'\s*[:：]\s*|\s+[-–—]\s+')


def base_title(title) -> str:
    """'One Piece (1999)' / 'One Piece Season 2' -> 'one piece'."""
    t = ' '.join(str(title or '').split()).casefold().strip()
    if not t:
        return ''
    # shortcut: subtitles after ':'/' - ' are dropped, so 'Re:Zero' -> 're';
    # refine with an alias table when that merge ever bites.
    t = _SEP.split(t)[0]
    while True:
        t2 = _TAIL.sub('', t).strip(' -–—,')
        if t2 == t:
            break
        t = t2
    return t


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def clamp_days(v, default: int = 14) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return v if v in DAYS else default


def clamp_limit(v, default: int) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return max(1, min(50, v))


def _clamped(d: dict) -> dict:
    """Merge over the defaults and hold every value inside its range."""
    got = d if isinstance(d, dict) else {}
    out = {k: dict(v) for k, v in DEFAULT_RAILS.items()}
    for sec, vals in out.items():
        for k in vals:
            if k in (got.get(sec) or {}):
                vals[k] = got[sec][k]
    out['continue']['limit'] = clamp_limit(out['continue']['limit'], 10)
    r, s = out['recent'], out['sidebar']
    r['days'] = clamp_days(r['days'])
    r['limit'] = clamp_limit(r['limit'], 20)
    r['include_new_seasons'] = bool(r['include_new_seasons'])
    s['days'] = clamp_days(s['days'])
    s['show_days'] = bool(s['show_days'])
    s['include_new_seasons'] = bool(s['include_new_seasons'])
    return out


def load_rails(cfg) -> dict:
    """ui.json -> window.rails, defaults filled in, values clamped."""
    try:
        d = load_json(cfg.ui) if cfg is not None else {}
    except Exception:
        d = {}
    return _clamped(((d or {}).get('window') or {}).get('rails') or {})


def save_rails(cfg, rails: dict) -> dict:
    """Write window.rails (clamped), keeping the other window keys."""
    out = _clamped(rails)
    d = load_json(cfg.ui) if cfg is not None else {}
    d = d if isinstance(d, dict) else {}
    win = d.get('window') if isinstance(d.get('window'), dict) else {}
    win['rails'] = out
    d['window'] = win
    save_json(cfg.ui, d)
    return out


def day_of(v):
    """ISO string/datetime -> date, or None (missing/junk air date)."""
    try:
        return date.fromisoformat(str(v or '')[:10])
    except (TypeError, ValueError):
        return None


def _newest_aired(eps):
    """(date, episode) of the newest AIRED episode in a Simkl episode list."""
    best = None
    for e in eps or []:
        if not e.get('aired'):
            continue
        d = day_of(e.get('date'))
        if d is None:
            continue
        key = (d, _int(e.get('episode')))
        if best is None or key > best:
            best = key
    return best


def _ids_hit(rel, ids) -> bool:
    got = (rel or {}).get('ids') or {}
    return any(str(got.get(k)) in ids for k in ('simkl', 'mal', 'anilist'))


def _watched_ids(rows) -> set:
    """Every id (simkl/mal/anilist) of a show he has actually watched."""
    out = set()
    for r in rows or []:
        if not (r.get('last_watched') or _int(r.get('watched'))):
            continue
        for k in ('simkl', 'mal', 'anilist'):
            if r.get(k):
                out.add(str(r[k]))
    return out


def _new_by_relations(simkl, known_ids: set, relations) -> bool:
    """True when Simkl's relation graph says this row is a later season.

    Simkl lists relations from the queried show's point of view, so a new
    season carries a direct `prequel` to the season he watched; the same fact
    seen from the watched show is a direct `sequel`. Both shapes are accepted
    (prequels / side stories of a watched show are NOT new seasons).
    """
    if not relations or not simkl:
        return False
    rels = relations.get(simkl) or relations.get(str(simkl)) or []
    for r in rels:                       # this row's own prequel link
        if r.get('is_direct') and r.get('relation_type') == 'prequel' \
                and _ids_hit(r, known_ids):
            return True
    sid = str(simkl)
    for key, links in relations.items():  # a watched show lists this row
        if str(key) not in known_ids:
            continue
        for r in links or []:
            if r.get('is_direct') and r.get('relation_type') == 'sequel' \
                    and _ids_hit(r, {sid}):
                return True
    return False


class RecentlyAired:
    """Aired-in-the-window shows for the second shelf rail."""

    def __init__(self, cfg, http=None, art: CoverArt = None):
        self.cfg = cfg
        self.http = http
        self.art = art or (CoverArt(cfg, http) if cfg is not None else None)

    def items(self, rows: List[dict], *, days: int = 14,
              include_new_seasons: bool = True, limit: int = 20,
              known_titles=(), relations=None,
              episodes=None) -> List[dict]:
        """`relations`/`episodes` are already-fetched maps keyed by simkl id
        (tp.simkl_extra) - this function itself never touches the network."""
        days = clamp_days(days)
        limit = clamp_limit(limit, 20)
        today = date.today()
        oldest = today - timedelta(days=days)
        known = {base_title(t) for t in known_titles or ()} - {''}
        known_ids = _watched_ids(rows)
        best = {}                            # base -> (key, item)
        for r in rows or []:
            title = r.get('title') or ''
            base = base_title(title)
            if not base:
                continue
            simkl = r.get('simkl')
            newest = _newest_aired((episodes or {}).get(simkl) or
                                   (episodes or {}).get(str(simkl)))
            d = newest[0] if newest else day_of(r.get('air_date'))
            if d is None or not (oldest <= d <= today):
                continue
            watched = _int(r.get('watched'))
            total = _int(r.get('total'))
            nxt = _int(r.get('next_ep'))
            rel_new = _new_by_relations(simkl, known_ids, relations)
            is_new = rel_new or (base in known and (
                base != ' '.join(title.split()).casefold() or watched == 0))
            if not (watched > 0 or r.get('last_watched')
                    or (r.get('status') in ('watching', 'plantowatch')
                        and nxt >= 1)
                    or (include_new_seasons and (rel_new or base in known))):
                continue
            pct = (100.0 * watched / total) if total else 0.0
            item = {'title': title, 'base': base, 'next_ep': nxt,
                    'watched': watched, 'total': total,
                    'pct': max(0.0, min(100.0, pct)),
                    'mal': r.get('mal'), 'simkl': simkl,
                    'image': '', 'air_date': d.isoformat(),
                    'days_ago': max(0, (today - d).days),
                    'is_new_season': bool(is_new),
                    'behind': max(0, newest[1] - watched) if newest else 0,
                    'status': r.get('status'), 'poster': r.get('poster')}
            key = (d, nxt)
            if base not in best or key > best[base][0]:
                best[base] = (key, item)
        picked = sorted(best.values(), key=lambda kv: kv[0],
                        reverse=True)[:limit]

        need_mal = [int(kv[1]['mal']) for kv in picked
                    if not kv[1]['poster'] and kv[1].get('mal')]
        covers = {}
        if need_mal and self.art is not None:
            try:
                covers = self.art.covers(need_mal)
            except Exception:
                covers = {}
        out = []
        for _key, item in picked:
            poster = item.pop('poster') or ''
            if poster:
                item['image'] = SIMKL_POSTER.format(path=poster)
            elif item.get('mal'):
                item['image'] = covers.get(int(item['mal']), '')
            out.append(item)
        return out
