"""tp.providers.zoro - HiAnime (hianime.fm) servers, resolved without a browser.

The chain, all plain HTTP:
  /search?keyword=              -> watch slugs
  /api/theme/episode/list/<id>  -> html with data-number/data-id rows
  /api/theme/episode/servers?episodeId=<id> -> html with data-hash rows; the
                                   hash is base64 of the server's embed URL
  embed page                    -> window.__P = base64(XOR(json, XOR_KEY))
  payload.src                   -> master.m3u8, payload.subtitles -> vtt tracks

The master host wants the embed's own origin as Referer (403 otherwise).

shortcut: the site's own per-page episode numbering is used as-is and the
quality ladder is left to mpv (the master carries all renditions); add a
season offset map when a caller needs absolute episode numbers.
"""
import base64
import json
import os
import re
from urllib.parse import quote

from ..http import DEFAULT_UA, HttpClient
from ..sources import DirectSource
from ..features.audio import ZoroAudio
from ..features.quality import NoQuality
from ..features.servers import ZoroServers
from ..features.sizes import NoSizes
from ..features.titles import ZoroTitles
from ..features.warm import HlsWarm

# Probed in this order; the first one serving a search page wins and is cached
# for the process. TGP_ZORO_BASE overrides everything.
# FEED is a repo that only publishes a host after validating it, so its value
# leads the probe; the tuple is the hand-kept fallback when the feed is down.
FEED = ('https://raw.githubusercontent.com/niakw/NiakVIO/main/'
        'provider-domain-history.json')
MIRRORS = ('https://hianime.fm', 'https://hianime.at', 'https://hianime.nz')
XOR_KEY = b'otaku-embed-v1'
_BASE_OK = ''          # last mirror that answered a probe (per process)
WATCH = re.compile(r'href="(?:https?://[^/"]+)?(/watch/[^"]+)"[^>]*title="([^"]+)"')
EP = re.compile(r'data-number="(\d+)"\s*data-id="(\d+)"')
SRV = re.compile(r'data-type="([^"]+)"[^>]*?data-server-name="([^"]+)"'
                 r'[^>]*?data-hash="([^"]+)"', re.S)


def feed_hosts(http=None) -> list:
    """Hosts the domain-history feed currently lists for hianime."""
    try:
        h = http or HttpClient()
        doc = json.loads(h.open(h.request(FEED)).read())
        provs = doc.get('providers') or {}
        out = []
        for key, val in provs.items():
            cur = (val or {}).get('current') or {}
            if 'hianime' in f'{key} {cur.get("host") or ""}':
                url = str(cur.get('url') or '').rstrip('/')
                if url.startswith('http'):
                    out.append(url)
        return out
    except Exception:          # a feed that is down must not break playback
        return []


def open_payload(blob: str) -> dict:
    """window.__P -> the player payload (base64 over XOR'd utf-8 JSON)."""
    raw = base64.b64decode(blob)
    plain = bytes(b ^ XOR_KEY[i % len(XOR_KEY)] for i, b in enumerate(raw))
    return json.loads(plain.decode('utf-8'))


class ZoroProvider:
    """HiAnime page -> servers -> a direct HLS source with its subtitles."""

    audio = ZoroAudio()
    quality = NoQuality()
    servers = ZoroServers()
    sizes = NoSizes()
    titles = ZoroTitles()
    warm = HlsWarm()

    def __init__(self, target: str = '', quality=None, audio: str = 'dub',
                 http=None):
        self.http = http or HttpClient()
        self._base = ''
        # `zoro:<slug>` (search-hit routing) and watch links both land here
        if target.lower().startswith('zoro:'):
            target = target[5:]
        self.slug = '/' + target.split('/watch/', 1)[-1].lstrip('/') \
            if target else ''
        self.slug = self.slug.split('?')[0].split('ep=')[0].rstrip('/')
        self.audio_name = audio or 'dub'
        self.quality_name = quality
        self.groups = []
        self.title = self._page_title()
        self.mal_id = None

    def _page_title(self) -> str:
        """The watch page's own title, else a readable form of the slug."""
        if self.slug:
            try:
                body = self._get(self.base + self.slug if self.slug.startswith('/')
                                 else self.base + '/' + self.slug)
                m = re.search(r'<title>(.*?)</title>', body, re.S)
                if m:
                    t = m.group(1).split('|')[0]
                    t = re.sub(r'^\s*watch\s+', '', t, flags=re.I)
                    t = re.sub(r'\s*(English|Hindi)\s+(Sub|Dub|Subbed|Dubbed)\b.*$',
                               '', t, flags=re.I).strip()
                    if t:
                        return t
            except Exception:
                pass
        return ' '.join(w for w in self.slug.rsplit('/', 1)[-1].split('-')
                        if not w.isdigit()).title()

    # --- HTTP ------------------------------------------------------------
    @property
    def base(self) -> str:
        """A mirror that answers right now (probed once per process)."""
        global _BASE_OK
        if not self._base:
            forced = os.environ.get('TGP_ZORO_BASE')
            if not forced and _BASE_OK:
                self._base = _BASE_OK
                return self._base
            cands = [forced] if forced else \
                list(dict.fromkeys(feed_hosts(self.http) + list(MIRRORS)))
            for cand in cands:
                try:
                    if '/watch/' in self._get(cand + '/search?keyword=one'):
                        self._base = cand.rstrip('/')
                        if not forced:
                            _BASE_OK = self._base
                        break
                except Exception:
                    continue
            else:
                raise ValueError('zoro: no mirror answered '
                                 + ', '.join(cands))
        return self._base

    def _get(self, url: str, ref: str = '') -> str:
        ref = ref or (self._base + '/') if self._base else ref
        r = self.http.open(self.http.request(url, headers={
            'User-Agent': DEFAULT_UA, 'Referer': ref,
            'X-Requested-With': 'XMLHttpRequest'}))
        return r.read().decode('utf-8', 'replace')

    def search(self, query: str):
        """[(slug, title)] for `query`, site order, de-duplicated."""
        body = self._get(f'{self.base}/search?keyword={quote(query)}')
        out, seen = [], set()
        for slug, name in WATCH.findall(body):
            if slug not in seen:
                seen.add(slug)
                out.append((slug, name))
        return out

    def episode_ids(self, slug: str) -> dict:
        """{episode number: site episode id} for the page `slug`."""
        nid = slug.rstrip('/').rsplit('-', 1)[-1]
        html = json.loads(self._get(
            f'{self.base}/api/theme/episode/list/{nid}')).get('html', '')
        return {int(n): int(i) for n, i in EP.findall(html)}

    def server_rows(self, ep_id: int):
        """[(audio, server name, embed url)] as the site lists them."""
        html = json.loads(self._get(
            f'{self.base}/api/theme/episode/servers?episodeId={int(ep_id)}'
        )).get('html', '') if self.base else ''
        return [(t, n, base64.b64decode(h).decode())
                for t, n, h in SRV.findall(html)]

    # --- the session's provider surface ---------------------------------
    def set_audio(self, audio):
        self.audio_name = audio or self.audio_name
        return self

    def fetch_groups(self):
        """One label per server the site lists, in its order."""
        try:
            ids = self.episode_ids(self.slug)
            rows = self.server_rows(next(iter(ids.values())))
        except Exception:
            rows = []
        self.groups = [{'id': f'{name} ({audio})', 'provider': name,
                        'label': f'{name} ({audio})', 'audio': audio}
                       for audio, name, _embed in rows] or \
            [{'id': 'hi anime', 'provider': 'zoro', 'label': 'hi anime',
              'audio': self.audio_name}]
        return self.groups

    def select(self, quality=None):
        """A picked server label also picks its audio (sub vs dub)."""
        for g in self.groups or []:
            if quality and g.get('id') == quality:
                self.audio_name = g.get('audio') or self.audio_name
        return self

    def load(self):
        self.fetch_groups()
        self.select(self.quality_name)
        return self

    def episodes(self) -> dict:
        try:
            nums = sorted(self.episode_ids(self.slug))
        except Exception:
            nums = []
        return {n: f'Episode {n}' for n in nums}

    def display_name(self, num: int):
        return None

    def stream(self, num: int) -> DirectSource:
        """The episode's stream: chosen audio first, the other one next."""
        eid = self.episode_ids(self.slug)[int(num)]
        rows = self.server_rows(eid)
        order = [r for r in rows if r[0] == self.audio_name] \
            + [r for r in rows if r[0] != self.audio_name]
        last = None
        for audio, name, embed in order:
            try:
                return self._resolve(embed)
            except Exception as ex:      # a dead server must not end the walk
                last = ex
        raise ValueError(f'zoro: no server answered for ep {num} ({last})')

    def _resolve(self, embed: str) -> DirectSource:
        page = self._get(embed, embed)
        m = re.search(r'window\.__P="([^"]+)"', page)
        if not m:
            raise ValueError('zoro: embed carries no payload')
        data = open_payload(m.group(1))
        src = data.get('src') or ''
        if not src.startswith('http'):
            raise ValueError('zoro: payload names no stream')
        host = re.match(r'https?://[^/]+', embed)
        origin = (host.group(0) if host else '') + '/'
        subs = [(s.get('label') or s.get('lang') or 'subs', s['src'])
                for s in data.get('subtitles') or [] if s.get('src')]
        return DirectSource(src, {'Referer': origin, 'User-Agent': DEFAULT_UA},
                            subs)