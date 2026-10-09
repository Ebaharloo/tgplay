"""tp.providers.animex - animex.one catalog + HLS (sub/dub) sources.

AnimeGate hands out one ranged file per episode. AnimeX instead returns a
fresh, short-lived HLS playlist from a small JSON API:

    /anime/<slug>/__data.json          -> internal slug + AniList/MAL ids
    pp.../rest/api/episodes?id=<slug>  -> episode list (with titles)
    pp.../rest/api/servers?id=&epNum=  -> servers, split into sub/dub
    pp.../rest/api/sources?id=&epNum=&type=&providerId=
                                       -> HLS url + subtitle tracks

Whatever AnimeX reports is surfaced as a selectable option - every audio type
(sub/dub) crossed with every server it lists (nothing hardcoded). Because the
stream is HLS, this provider returns a DirectSource for mpv to play itself
(no local range proxy).
"""
import json
import re
from typing import Dict, List, Optional, Tuple

from ..http import HttpClient, DEFAULT_UA, _quiet_close
from ..sources import DirectSource
from .base import Provider

SITE = 'https://animex.one'
API = 'https://pp.animex.one'
# The media CDN whitelists this referer for the m3u8/segments.
MEDIA_REFERER = 'https://megaplay.buzz/'


def base_slug(url: str) -> str:
    """`.../anime/<slug>` or `.../watch/<slug>-episode-N` -> `<slug>`."""
    m = re.search(r'/(?:anime|watch)/([^/?#]+)', url or '')
    if not m:
        raise ValueError(f'not an animex link: {url}')
    return re.sub(r'-episode-\d+.*$', '', m.group(1))


def pretty_title(slug: str) -> str:
    words = re.sub(r'-\d+$', '', slug).replace('-', ' ').strip()
    return ' '.join(w.capitalize() if w.islower() else w for w in words.split())


def _dv(data: list, i):
    """Resolve one SvelteKit `devalue` reference (index into `data`)."""
    return data[i] if isinstance(i, int) and 0 <= i < len(data) else i


def _find_anime(obj):
    if isinstance(obj, dict):
        if 'slug' in obj and 'anilistId' in obj:
            return obj
        for v in obj.values():
            r = _find_anime(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_anime(v)
            if r is not None:
                return r
    return None


class AnimeXProvider(Provider):
    def __init__(self, url: str, quality=None, audio: str = 'dub',
                 provider: Optional[str] = None, http: Optional[HttpClient] = None):
        self.url = url
        self.quality = quality
        self.audio = (audio or 'dub').lower()
        self.provider = provider
        self.http = http or HttpClient()
        self.title = pretty_title(base_slug(url))
        self.slug: Optional[str] = None
        self.anilist_id = None
        self.mal_id = None
        self.groups: List[dict] = []
        self._providers: Dict[str, List[str]] = {'dub': [], 'sub': []}
        self._tips: Dict[str, str] = {}
        self._eps: Dict[int, str] = {}
        self._audio = self.audio
        self._pid: Optional[str] = provider
        self._resolved = False
        self._loaded = False

    # --- low level ------------------------------------------------------
    def _json(self, url: str):
        r = self.http.open(self.http.request(
            url, headers={'Referer': SITE + '/', 'Accept': 'application/json'}))
        try:
            return json.loads(r.read().decode('utf-8', 'replace'))
        finally:
            _quiet_close(r)

    def _resolve(self):
        if self._resolved:
            return
        d = self._json(f'{SITE}/anime/{base_slug(self.url)}/__data.json')
        data = d.get('nodes', [None, {}])[1].get('data', [])
        rec = _find_anime(data) or {}
        self.slug = _dv(data, rec.get('slug')) or base_slug(self.url)
        self.anilist_id = _dv(data, rec.get('anilistId'))
        self.mal_id = _dv(data, rec.get('malId'))
        t = _dv(data, rec.get('titleEnglish')) or _dv(data, rec.get('titleRomaji'))
        if t:
            self.title = str(t)
        self._resolved = True

    # --- catalog --------------------------------------------------------
    def fetch_groups(self) -> List[dict]:
        self._resolve()
        srv = self._json(f'{API}/rest/api/servers?id={self.slug}&epNum=1')
        self._providers = {'dub': [], 'sub': []}
        self._tips = {}
        for key, audio in (('dubProviders', 'dub'), ('subProviders', 'sub')):
            for p in srv.get(key) or []:
                pid = str(p.get('id') or '').strip()
                if not pid:
                    continue
                if pid not in self._providers[audio]:
                    self._providers[audio].append(pid)
                self._tips.setdefault(pid, str(p.get('tip') or ''))
        groups: List[dict] = []
        seen = set()
        for audio in ('dub', 'sub'):          # dub first = the default
            for pid in self._providers[audio]:
                lab = f'{audio.upper()} · {pid}'
                if lab in seen:
                    continue
                seen.add(lab)
                groups.append({'id': lab, 'label': lab, 'audio': audio,
                               'provider': pid})
        self.groups = groups
        return groups

    def select(self, quality=None):
        self._resolve()
        if not self.groups:
            self.fetch_groups()
        self._audio, self._pid = self._parse_choice(quality)
        self._loaded = False
        return self

    def rotate(self) -> bool:
        """Advance to the next server of the current audio (used when mpv
        fails to open one). Returns False when there is nowhere to go."""
        order = [p for p in self._providers.get(self._audio, []) if p]
        if len(order) <= 1:
            return False
        try:
            i = order.index(self._pid)
        except ValueError:
            i = -1
        self._pid = order[(i + 1) % len(order)]
        return True

    def _parse_choice(self, choice) -> Tuple[str, str]:
        if choice:
            m = re.match(r'\s*(SUB|DUB)\s*[·:.\-]*\s*([A-Za-z0-9_]+)',
                         str(choice), re.I)
            if m:
                audio, pid = m.group(1).lower(), m.group(2)
                if pid in self._providers.get(audio, []):
                    return audio, pid
        audio = self.audio if self._providers.get(self.audio) else (
            'dub' if self._providers.get('dub') else 'sub')
        return audio, (self._providers.get(audio) or [None])[0]

    def load(self):
        self._resolve()
        if not self.groups:
            self.fetch_groups()
        if self._pid is None:
            self.select(self.quality)
        self._load_eps()
        self._loaded = True
        return self

    def _load_eps(self):
        if self._eps:
            return
        d = self._json(f'{API}/rest/api/episodes?id={self.slug}')
        out: Dict[int, str] = {}
        if isinstance(d, list):
            for e in d:
                try:
                    n = int(e.get('number'))
                except Exception:
                    continue
                t = None
                tt = e.get('titles')
                if isinstance(tt, dict):
                    t = tt.get('en') or tt.get('x-jat') or tt.get('ja')
                out[n] = str(t or e.get('title') or f'Episode {n}')
        self._eps = dict(sorted(out.items()))

    def episodes(self) -> Dict[int, str]:
        if not self._loaded:
            self.load()
        return dict(self._eps)

    def display_name(self, num: int):
        if self._eps:
            return self._eps.get(num)
        return None

    # --- playback -------------------------------------------------------
    def _probe(self, url: str) -> bool:
        """True when the media CDN actually serves this URL to us (some
        servers' tokens are bound to the browser and answer 'forbidden')."""
        try:
            r = self.http.open(self.http.request(url, headers={
                'Referer': MEDIA_REFERER, 'User-Agent': DEFAULT_UA,
                'Accept': '*/*', 'Range': 'bytes=0-1023'}))
            try:
                head = r.read(16)
            finally:
                _quiet_close(r)
            return b'#EXTM3U' in head
        except Exception:
            return False

    def stream(self, num: int) -> DirectSource:
        if not self._loaded:
            self.load()
        order = [self._pid] + [p for p in self._providers.get(self._audio, [])
                               if p and p != self._pid]
        last = None
        for pid in [p for p in order if p]:
            try:
                d = self._json(
                    f'{API}/rest/api/sources?id={self.slug}&epNum={num}'
                    f'&type={self._audio}&providerId={pid}')
            except Exception as ex:
                last = ex
                continue
            url = next((s.get('url') for s in (d.get('sources') or [])
                        if s.get('url')), None)
            if not url or not self._probe(url):
                last = RuntimeError(f'{pid}: not serving')
                continue
            subs = []
            if self._audio == 'sub':
                for tr in (d.get('tracks') or []):
                    if str(tr.get('lang') or '').lower().startswith('en') and tr.get('url'):
                        subs.append((tr.get('label') or 'English', tr['url']))
            self._pid = pid            # remember the server that worked
            return DirectSource(url,
                                headers={'Referer': MEDIA_REFERER,
                                         'User-Agent': DEFAULT_UA},
                                subs=subs)
        raise RuntimeError(f'animex: no playable source for ep{num} ({last})')

