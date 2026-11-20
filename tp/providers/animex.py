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
from typing import Dict, List, Optional

from .. import log
from ..http import HttpClient, DEFAULT_UA, _quiet_close
from ..sources import DirectSource
from ..features.audio import AxpAudio
from ..features.quality import AxpQuality
from ..features.servers import AxpServers
from ..features.sizes import NoSizes
from ..features.titles import AxpTitles
from .base import NoServersYet, Provider

SITE = 'https://animex.one'
API = 'https://pp.animex.one'
GRAPHQL = 'https://graphql.animex.one/graphql'
# The media CDN whitelists this referer for the m3u8/segments.
MEDIA_REFERER = 'https://megaplay.buzz/'
# Each media host whitelists a different referer, so remember which one worked
# per host: megavid wants the site, drama top wants itself, nexabloom wants
# MEDIA_REFERER. Keyed by host only - same host = same rule in practice.
_HDRS: Dict[str, dict] = {}


def base_slug(url: str) -> str:
    """Accept a watch/anime URL, an `axp:<slug>` id, or a bare internal slug."""
    s = (url or '').strip()
    if s.lower().startswith('axp:'):
        return s[4:]
    m = re.search(r'/(?:anime|watch)/([^/?#]+)', s)
    if m:
        return re.sub(r'-episode-\d+.*$', '', m.group(1))
    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]+', s):
        return s
    raise ValueError(f'not an animex link: {url}')


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
    audio = AxpAudio()
    quality = AxpQuality()
    servers = AxpServers()
    sizes = NoSizes()
    titles = AxpTitles()

    def __init__(self, url: str, quality=None, audio: str = 'dub',
                 provider: Optional[str] = None, http: Optional[HttpClient] = None):
        self.url = url
        self.quality_name = quality
        self.audio_name = (audio or 'dub').lower()
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
        self._audio = self.audio_name
        self._pid: Optional[str] = provider
        self._pref: Optional[str] = provider
        self._size_pref: Optional[str] = None
        self._chosen = False
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
        raw = (self.url or '').strip()
        internal = (raw.lower().startswith('axp:')
                    or ('://' not in raw and '/' not in raw
                        and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]+', raw)
                        is not None))
        cand = base_slug(raw)
        if internal:
            # Already the AnimeX internal slug (from search): trust it. Asking
            # the site's /anime/<slug>/__data.json for an internal slug returns
            # a *different* show, so metadata comes from GraphQL instead.
            self.slug = cand
            meta = self._anime(cand) or {}
            self.anilist_id = meta.get('anilistId')
            self.mal_id = meta.get('malId')
            t = meta.get('titleEnglish') or meta.get('titleRomaji')
            if t:
                self.title = str(t)
            self._resolved = True
            return
        rec, data = None, []
        try:
            d = self._json(f'{SITE}/anime/{cand}/__data.json')
            data = d.get('nodes', [None, {}])[1].get('data', [])
            rec = _find_anime(data)
        except Exception:
            rec = None
        if rec:
            self.slug = _dv(data, rec.get('slug')) or cand
            self.anilist_id = _dv(data, rec.get('anilistId'))
            self.mal_id = _dv(data, rec.get('malId'))
            t = _dv(data, rec.get('titleEnglish')) or _dv(data, rec.get('titleRomaji'))
            if t:
                self.title = str(t)
        else:
            self.slug = cand
            meta = self._anime(cand) or {}
            self.anilist_id = meta.get('anilistId')
            self.mal_id = meta.get('malId')
            t = meta.get('titleEnglish') or meta.get('titleRomaji')
            if t:
                self.title = str(t)
        self._resolved = True

    def _anime(self, slug: str) -> Optional[dict]:
        q = ('{ anime(id:%s){ id titleEnglish titleRomaji anilistId malId } }'
             % json.dumps(slug))
        try:
            d = self._graphql(q)
            return ((d.get('data') or {}).get('anime')) or None
        except Exception:
            return None

    def _graphql(self, query: str) -> dict:
        body = json.dumps({'query': query}).encode()
        r = self.http.open(self.http.request(
            GRAPHQL, headers={'Referer': SITE + '/',
                              'Content-Type': 'application/json',
                              'Accept': 'application/json'},
            method='POST', data=body))
        try:
            return json.loads(r.read().decode('utf-8', 'replace'))
        finally:
            _quiet_close(r)

    # --- catalog --------------------------------------------------------
    def headers_for(self, url: str) -> dict:
        """Headers that actually get this media host to serve the playlist."""
        host = re.sub(r'^[a-z]+://([^/]+).*$', r'\1', url or '')
        if host in _HDRS:
            return _HDRS[host]
        own = f'https://{host}/'
        for hd in ({'Referer': MEDIA_REFERER, 'User-Agent': DEFAULT_UA},
                   {'Referer': SITE + '/', 'User-Agent': DEFAULT_UA},
                   {'Referer': own, 'User-Agent': DEFAULT_UA},
                   {'User-Agent': DEFAULT_UA}):
            try:
                r = self.http.open(self.http.request(url, headers=dict(
                    hd, Accept='*/*', Range='bytes=0-1023')))
                try:
                    ok = b'#EXTM3U' in r.read(16)
                finally:
                    _quiet_close(r)
                if ok:
                    _HDRS[host] = hd
                    return hd
            except Exception:
                continue
        return {'Referer': MEDIA_REFERER, 'User-Agent': DEFAULT_UA}

    def _m3u8_qualities(self, url) -> list:
        """All HLS rendition sizes of one server (e.g. ['1080p','720p','480p'])."""
        try:
            r = self.http.open(self.http.request(url, headers=dict(
                self.headers_for(url), Accept='*/*')))
            body = r.read().decode('utf-8', 'replace')
        except Exception:
            return []
        out = []
        for line in body.splitlines():
            if line.startswith('#EXT-X-STREAM-INF'):
                m = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
                if m:
                    q = f'{m.group(2)}p'
                    if q not in out:
                        out.append(q)
                elif not out:
                    bw = re.search(r'BANDWIDTH=(\d+)', line)
                    if bw:
                        out.append(f'~{int(bw.group(1)) // 1000000:.0f}Mbps')
        return out

    def _m3u8_quality(self, url) -> str:
        qs = self._m3u8_qualities(url)
        return qs[0] if qs else ''

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
        order: List[str] = []
        for audio in ('dub', 'sub'):          # dub-capable servers first
            for pid in self._providers[audio]:
                if pid not in order:
                    order.append(pid)
        groups: List[dict] = []
        for pid in order:
            tags = [a for a in ('dub', 'sub') if pid in self._providers[a]]
            label = f"{pid}  ({'+'.join(tags)})"
            qualities: List[str] = []
            # the video size(s), the way AGP lists 480P/720P/1080P: probe ONE
            # episode of that server and read the HLS rendition(s)
            try:
                d = self._json(f'{API}/rest/api/sources?id={self.slug}'
                               f'&epNum=1&type={"sub" if pid not in self._providers["dub"] else "dub"}'
                               f'&providerId={pid}')
                url = next((s.get('url') for s in (d.get('sources') or [])
                            if s.get('url')), None)
                if url:
                    qualities = self._m3u8_qualities(url)
                    if qualities:
                        label = f"{pid}  ({'+'.join(tags)})  ·  {qualities[0]}"
                    elif not self._probe(url):
                        # listed by the API but refuses every request we can
                        # make: say so instead of offering a dead pick
                        label += '  ·  not serving'
            except Exception:
                label += '  ·  not serving'
            groups.append({'id': pid, 'provider': pid, 'label': label,
                           'qualities': qualities})
        self.groups = groups
        return groups

    def set_audio(self, audio):
        """Preferred audio: 'dub' (default), 'sub', or 'auto' (dub if present)."""
        a = (audio or 'dub').lower()
        self.audio_name = a if a in ('dub', 'sub', 'auto') else 'dub'
        self._chosen = False
        self._loaded = False
        return self

    def select(self, quality=None):
        self._resolve()
        if not self.groups:
            self.fetch_groups()
        self._pref = self._parse_server(quality)
        # remember a requested rendition (e.g. "720p") if present
        self._size_pref = self.quality.size_pref(quality) or None
        self._resolve_audio()
        if not self._providers.get(self._audio) \
                and not self._providers.get('dub') \
                and not self._providers.get('sub'):
            raise NoServersYet(
                f'"{self.title}" has no dub/sub streams on AnimeX yet'
                ' — try another link or source')
        self._chosen = True
        self._loaded = False
        return self

    def _parse_server(self, choice) -> Optional[str]:
        """Map a menu label ('nero  (dub+sub)' / 'nero' / None) to a server id."""
        if not choice:
            return None
        s = str(choice).strip()
        for pid in (self._providers.get('dub', []) + self._providers.get('sub', [])):
            if s == pid or s.startswith(pid + ' ') or s.startswith(pid + '('):
                return pid
        m = re.match(r'([A-Za-z0-9_]+)', s)
        return m.group(1) if m else None

    def _resolve_audio(self):
        """Pick the final (audio, server); warn + fall back when an audio
        isn't available (e.g. a title with no dub starts in sub)."""
        want = self.audio_name
        provs = self._providers
        if want == 'auto':
            want = 'dub' if provs.get('dub') else 'sub'
        if not provs.get(want):
            other = 'sub' if want == 'dub' else 'dub'
            if provs.get(other):
                log.cprint(f'animex: no {want} for "{self.title}" '
                           f'— starting with {other}')
                want = other
        order = [p for p in provs.get(want, []) if p]
        pid = self._pref if self._pref in order else (order[0] if order else None)
        self._audio, self._pid = want, pid

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

    def load(self):
        self._resolve()
        if not self.groups:
            self.fetch_groups()
        if not self._chosen:
            self.select(self.quality_name)
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
            r = self.http.open(self.http.request(url, headers=dict(
                self.headers_for(url), Accept='*/*', Range='bytes=0-1023')))
            try:
                head = r.read(16)
            finally:
                _quiet_close(r)
            return b'#EXTM3U' in head
        except Exception:
            return False

    def _audio_dead(self, master_url: str) -> bool:
        """True when the master lists audio renditions and none of them load.

        This is the silent-video case: the dub master still answers, but its
        audio playlist is gone, so mpv plays picture with no sound."""
        try:
            r = self.http.open(self.http.request(master_url, headers=dict(
                self.headers_for(master_url), Accept='*/*')))
            body = r.read().decode('utf-8', 'replace')
        except Exception:
            return False                  # cannot tell: let mpv try
        from urllib.parse import urljoin, urlsplit
        uris = [m.group(1) for m in re.finditer(
            r'#EXT-X-MEDIA:[^\n]*TYPE=AUDIO[^\n]*URI="([^"]+)"', body)]
        if not uris:
            return False                  # media playlist: no audio group here
        for u in uris:
            full = urljoin(master_url, u)
            if '?' not in full and '?' in master_url:
                full += '?' + urlsplit(master_url).query
            if self._probe(full):
                return False
        return True

    def _rendition_url(self, master_url: str, want: str) -> Optional[str]:
        """Resolve a master m3u8 to the media playlist for the requested size."""
        want = (want or '').lower()
        try:
            r = self.http.open(self.http.request(master_url, headers=dict(
                self.headers_for(master_url), Accept='*/*')))
            body = r.read().decode('utf-8', 'replace')
        except Exception:
            return None
        lines = body.splitlines()
        for i, line in enumerate(lines):
            if not line.startswith('#EXT-X-STREAM-INF'):
                continue
            m = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
            size = f'{m.group(2)}p' if m else ''
            name_m = re.search(r'NAME="([^"]+)"', line)
            name = name_m.group(1).lower() if name_m else ''
            if want and want not in (size.lower(), name):
                continue
            # next non-empty, non-comment line is the media playlist
            for j in range(i + 1, len(lines)):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith('#'):
                    from urllib.parse import urljoin, urlsplit
                    resolved = urljoin(master_url, nxt)
                    # preserve the signed token (it lives in the master URL's query)
                    if '?' not in resolved and '?' in master_url:
                        resolved = resolved + '?' + urlsplit(master_url).query
                    return resolved
            break
        return None

    def stream(self, num: int) -> DirectSource:
        if not self._loaded:
            self.load()
        want = self._audio
        # dub first, then the other audio type: a show can have dub on ep 3
        # and none on ep 4, and a dead dub audio track plays as silent video
        tried = []
        for aud in [want, 'sub' if want == 'dub' else 'dub']:
            pids = [p for p in self._providers.get(aud, []) if p]
            if aud == want and self._pid in pids:      # preferred server first
                pids = [self._pid] + [p for p in pids if p != self._pid]
            tried += [(p, aud) for p in pids]
        last = None
        for pid, aud in tried:
            try:
                d = self._json(
                    f'{API}/rest/api/sources?id={self.slug}&epNum={num}'
                    f'&type={aud}&providerId={pid}')
            except Exception as ex:
                last = ex
                continue
            url = next((s.get('url') for s in (d.get('sources') or [])
                        if s.get('url')), None)
            if not url or not self._probe(url):
                last = RuntimeError(f'{pid}: not serving')
                continue
            if aud == 'dub' and self._audio_dead(url):
                last = RuntimeError(f'{pid}: dub audio track is dead')
                continue
            if aud != want:
                log.cprint(f'animex: ep{num} has no {want} - playing {aud}')
            # honor a chosen rendition size (e.g. "720p") by swapping the
            # master playlist for that rendition's media playlist
            if self._size_pref:
                want = self._size_pref
                resolved = self._rendition_url(url, want)
                if resolved:
                    url = resolved
            subs = []
            if aud == 'sub':
                for tr in (d.get('tracks') or []):
                    if str(tr.get('lang') or '').lower().startswith('en') and tr.get('url'):
                        subs.append((tr.get('label') or 'English', tr['url']))
            self._pid = pid            # remember the server that worked
            return DirectSource(url, headers=dict(self.headers_for(url)),
                                subs=subs)
        raise RuntimeError(f'animex: no playable source for ep{num} ({last})')


def search(query: str, http=None, limit: int = 12) -> List[dict]:
    """AnimeX GraphQL search -> [{'title','url','source'}] (url = `axp:<slug>`)."""
    q = (query or '').strip()
    if not q:
        return []
    http = http or HttpClient()
    gql = ('{ searchAnime(query:%s, limit:%d){ items '
           '{ id titleEnglish titleRomaji anilistId malId } } }'
           % (json.dumps(q), int(limit)))
    body = json.dumps({'query': gql}).encode()
    r = http.open(http.request(
        GRAPHQL, headers={'Referer': SITE + '/',
                          'Content-Type': 'application/json',
                          'Accept': 'application/json'},
        method='POST', data=body))
    try:
        d = json.loads(r.read().decode('utf-8', 'replace'))
    finally:
        _quiet_close(r)
    items = (((d.get('data') or {}).get('searchAnime') or {}).get('items')) or []
    out: List[dict] = []
    for it in items:
        sid = it.get('id')
        if not sid:
            continue
        out.append({'title': it.get('titleEnglish') or it.get('titleRomaji') or sid,
                    'url': f'axp:{sid}', 'source': 'axp',
                    'malId': it.get('malId'), 'anilistId': it.get('anilistId')})
    return out

