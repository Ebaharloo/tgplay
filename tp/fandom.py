"""tp.fandom - character rosters from series Fandom wikis (MediaWiki API).

AniList lists a handful of characters for many donghua / novels; the series'
own Fandom wiki (e.g. xian-ni.fandom.com for Renegade Immortal) keeps the
full cast in `Category:Characters`. This module:

  * finds the right wiki by trying the show's name forms as subdomains,
  * reads `Category:Characters` (names + links),
  * batch-fetches thumbnails (PageImages) so the cast dialog can show photos,
  * returns our normal row shape tagged `from='wiki'`.

No API key; a handful of small GETs per show, and cached by the cast service
for a month.
"""
import json
import re
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

MAX_ROWS = 250

_UA = 'Mozilla/5.0 (tgplay/1.0 character lookup)'


def _slug(text: str) -> str:
    s = (text or '').lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def wiki_candidates(titles: List[str]) -> List[str]:
    """Subdomain guesses for a show, most-likely first, deduped."""
    out = []
    for t in titles or []:
        if not t:
            continue
        s = _slug(t)
        if len(s) < 3:
            continue
        for cand in (s, s.replace('-', ''), s + '-wiki'):
            if cand and cand not in out:
                out.append(cand)
    return out[:8]


class FandomCharacters:
    def __init__(self, http=None, timeout: int = 12):
        self.timeout = timeout

    # --- low level --------------------------------------------------------
    def _api(self, sub: str, params: Dict[str, str]) -> Optional[dict]:
        url = (f'https://{sub}.fandom.com/api.php?' +
               urllib.parse.urlencode({'format': 'json', **params}))
        try:
            req = urllib.request.Request(url, headers={'User-Agent': _UA})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except Exception:
            return None

    def _page_url(self, sub: str, title: str) -> str:
        return (f'https://{sub}.fandom.com/wiki/'
                + urllib.parse.quote(str(title).replace(' ', '_')))

    def _thumbs(self, sub: str, titles: List[str]) -> Dict[str, str]:
        """{title: thumbnail url} in batches (PageImages extension)."""
        out: Dict[str, str] = {}
        for i in range(0, len(titles), 40):
            batch = titles[i:i + 40]
            d = self._api(sub, {
                'action': 'query', 'prop': 'pageimages',
                'piprop': 'thumbnail', 'pithumbsize': '200',
                'titles': '|'.join(batch),
                'redirects': '1'})
            pages = ((d or {}).get('query') or {}).get('pages') or {}
            for page in pages.values():
                t = page.get('title')
                th = ((page.get('thumbnail') or {}).get('source'))
                if t and th and 'no-image-available' not in th.lower():
                    out[t] = th           # skip Fandom's generic placeholder
        return out

    # --- public -----------------------------------------------------------
    def fetch(self, titles: List[str], limit: int = MAX_ROWS) -> List[dict]:
        """Full `Category:Characters` roster from the first matching wiki."""
        for sub in wiki_candidates(titles):
            d = self._api(sub, {'action': 'query', 'list': 'categorymembers',
                                'cmtitle': 'Category:Characters',
                                'cmlimit': '500', 'cmnamespace': '0'})
            members = ((d or {}).get('query') or {}).get('categorymembers')
            if not members:
                continue
            names = []
            for m in members:
                t = str(m.get('title') or '').strip()
                if not t or t.lower() in ('characters', 'main characters'):
                    continue
                names.append(t)
            if len(names) < 3:
                continue
            names = names[:limit]
            thumbs = self._thumbs(sub, names)
            rows = []
            for t in names:
                rows.append({
                    'cid': f'fandom:{sub}/{t}',
                    'name': t,
                    'native': '',
                    'role': '',
                    'image': thumbs.get(t, ''),
                    'fav': 0,
                    'desc': '',
                    'url': self._page_url(sub, t),
                    'va': '',
                    'va_lang': '',
                    'from': 'wiki',
                    'wiki': sub,
                })
            if rows:
                return rows
        return []
