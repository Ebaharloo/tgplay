"""tp.web.server - the local HTTP surface the Astryx window talks to.

One `ThreadingHTTPServer` on 127.0.0.1. Every long job (library, search, show
load, playback) runs on a worker thread and the handler answers at once with
the current snapshot, so nothing here blocks for more than a moment. All the
real work stays in `tp.*`: this module only glues it to JSON, calling exactly
what `tp/gui_all.py` calls for the Qt window.

Endpoints (PLAN-WEB.md): GET /api/state, GET /api/events (SSE),
POST /api/search, /api/open, /api/play, /api/stop, /api/options, /api/settings;
everything else is `web/dist` (the built bundle).

`TPLAY_FAKE=1` serves `FakeLibrary`/`FakeSession` below: the same JSON the
tests use, no network - for screenshots and poking at the UI.
"""
import json
import os
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .. import log
from ..config import Config
from ..options import PlaybackOptions, form_fields, form_result
from ..recent import load_rails, save_rails

HOST = '127.0.0.1'
PORT = 8799
SOURCES = ('agp', 'axp', 'tgp', 'tg')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIST = os.path.join(ROOT, 'web', 'dist')

TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript',
         '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml',
         '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
         '.map': 'application/json'}

MISSING = """<!doctype html><meta charset="utf-8"><title>tgplay</title>
<body style="font:14px/1.5 system-ui;padding:2rem;background:#17181c;color:#d7dae0">
<h2>web bundle missing</h2><p>Build the Astryx app once:</p>
<pre style="background:#22242a;padding:1rem;border-radius:8px">cd web &amp;&amp; npm run build</pre>
<p>Then reload this page.</p></body>"""


class AppState:
    """Everything the window renders, plus the worker threads that fill it."""

    def __init__(self, cfg=None, http=None, loader=None, overview=None,
                 probe=None, finder=None, extra=True):
        self.cfg = cfg or Config()
        self.http = http
        self.extra = extra
        self._loader = loader or self._load_real
        self._overview = overview or self._overview_real
        self._probe = probe or self._probe_real
        self._finder = finder or self._find_real
        self.lock = threading.RLock()
        self.session = None
        self.loading = False
        self.playing = False
        self.message = ''
        self.search = {'q': '', 'results': [], 'busy': False}
        self.rails = self._load_rails()
        self.rails_items = {'continue': [], 'recent': []}
        self.feed = []
        self.upcoming = []
        self.history = []
        self.lights = {'simkl': 'warn', 'gate': 'warn', 'anilist': 'warn'}
        self.lines = []                      # log ring, streamed by /api/events
        self._lib_thread = None
        log.SINK = self._sink                # the window's log mirror

    # --- injectable seams (tests pass stubs) ------------------------------
    def _load_rails(self) -> dict:
        try:
            return load_rails(self.cfg)
        except Exception as ex:
            log.cprint(f'web: rails settings unreadable ({ex})')
            return {}

    def _load_real(self, src, target):
        from ..session import SessionLoader
        return SessionLoader(self.cfg, self.http)(src, target)

    def _overview_real(self):
        from ..library import overview
        return overview(self.cfg, self.http)

    def _probe_real(self):
        from ..status import StatusProbe
        return StatusProbe(self.cfg, self.http).check_all()

    def _find_real(self, q):
        from ..finder import ShowFinder
        return ShowFinder(self.cfg, self.http).find(title=q)

    # --- log mirror -------------------------------------------------------
    def _sink(self, line):
        with self.lock:
            self.lines.append(str(line))
            del self.lines[:-500]

    def _say(self, msg: str):
        with self.lock:
            self.message = msg

    # --- library ----------------------------------------------------------
    def start(self):
        self.refresh_library()

    def refresh_library(self):
        """Queue one library refresh; repeat calls while it runs are ignored."""
        with self.lock:
            if self._lib_thread is not None and self._lib_thread.is_alive():
                return
            self._lib_thread = threading.Thread(target=self._library_worker,
                                                daemon=True)
            self._lib_thread.start()

    def _library_worker(self):
        lights = dict(self.lights)
        try:
            for it in self._probe() or []:
                lights[it.get('key')] = it.get('state') or 'warn'
        except Exception as ex:
            log.cprint(f'web: status probe failed ({ex})')
        rails = self._load_rails()
        window = int((rails.get('recent') or {}).get('days') or 14)
        try:
            try:
                ov = self._overview(aired_days=window) or {}
            except TypeError:          # stubs without the kwarg
                ov = self._overview() or {}
        except Exception as ex:
            log.cprint(f'feed: fetch failed ({ex})')
            with self.lock:
                self.lights = lights
                self.message = f'library failed: {ex}'
            return
        rem, rows = ov.get('rem') or [], ov.get('rows') or []
        # library rows for upcoming use air_date/next_ep (not date/episode)
        upcoming = [{'date': str(c.get('air_date') or '')[:10],
                     'ep': c.get('next_ep'),
                     'title': c.get('title') or '',
                     'ep_title': c.get('ep_title') or '',
                     'kind': c.get('kind') or 'upcoming'}
                    for c in ov.get('cal') or []
                    if c.get('air_date')
                    and str(c.get('air_date'))[:10] >= date.today().isoformat()]
        shelf, recent = [], []
        try:
            from ..continuewatch import ContinueWatching
            from ..recent import RecentlyAired
            shelf = ContinueWatching(self.cfg, self.http).items(
                rem, limit=(rails.get('continue') or {}).get('limit', 10))
            window = max((rails.get('recent') or {}).get('days', 14),
                         (rails.get('sidebar') or {}).get('days', 14))
            rel, eps, det = self._extra(rows, window)
            known = [r['title'] for r in rows
                     if r.get('title') and (r.get('last_watched')
                                            or int(r.get('watched') or 0) > 0)]
            from ..recent import _newest_aired, day_of
            def _air(r):
                sid = r.get('simkl')
                n = _newest_aired(eps.get(sid) or eps.get(str(sid)) or [])
                if n:
                    return n[0].isoformat(), n[1]
                d = (det.get(sid) or {}).get('last_aired')
                if d:
                    return d, None
                return r.get('air_date'), None
            aired, enriched = [], []
            for r in rows:
                when, newest_ep = _air(r)
                d = day_of(when)
                if d is None:
                    enriched.append(dict(r, air_date=when))
                    continue
                enriched.append(dict(r, air_date=when))
                age = (date.today() - d).days
                if 0 <= age <= window:
                    aired.append({'date': when[:10], 'days': age,
                                  'ep': newest_ep or r.get('next_ep'),
                                  'title': r.get('title') or '',
                                  'new': bool(det.get(r.get('simkl'), {})
                                              .get('status') == 'airing'
                                              and int(r.get('watched') or 0) == 0)})
            for c in ov.get('cal') or []:
                when = str(c.get('air_date') or '')
                d = day_of(when)
                if d is None or d > date.today():
                    continue
                age = (date.today() - d).days
                if 0 <= age <= window:
                    aired.append({'date': when[:10], 'days': age,
                                  'ep': c.get('next_ep'),
                                  'title': c.get('title') or '',
                                  'new': False})
            uniq = {}
            for a in aired:                       # calendar + rows overlap
                uniq.setdefault((a['date'], a['title']), a)
            aired = list(uniq.values())
            aired.sort(key=lambda x: x['date'], reverse=True)
            recent = RecentlyAired(self.cfg, self.http).items(
                enriched, days=window, limit=50, known_titles=known,
                relations=rel, episodes=eps)
        except Exception as ex:
            log.cprint(f'feed: poster rails failed ({ex})')
            with self.lock:
                self.message = f'rails failed: {ex}'
        with self.lock:
            self.lights = lights
            self.upcoming = upcoming
            self.rails = rails
            self.rails_items = {'continue': shelf, 'recent': recent}
            self.feed = aired[:60]
            self.history = [{'watched': str(h.get('last_watched') or '')[:10],
                             'prog': f"{int(h.get('watched') or 0)}/"
                                     f"{int(h.get('total') or 0)}",
                             'title': h.get('title') or ''}
                            for h in ov.get('hist') or []]
            if not (shelf or recent or self.history):
                self.message = ('library is empty - is Simkl connected?')

    def _extra(self, rows, days):
        """relations + episode lists for the rail (cached by tp.simkl_extra).

        shortcut: the ancestor filter of gui_all._fetch_extra is skipped (first
        60 simkl ids win); add the watched-first ordering when a large library
        starts losing bots to the cap.
        """
        if not self.extra or not rows:
            return {}, {}, {}
        from ..simkl_extra import SimklExtra
        ex = SimklExtra(self.cfg, self.http)
        rel, eps, det = {}, {}, {}
        cands = []
        for r in rows or []:
            sid = r.get('simkl')
            if not sid:
                continue
            started = (int(r.get('watched') or 0) > 0 or r.get('last_watched')
                       or r.get('status') in ('watching', 'plantowatch'))
            if not started:
                continue
            cands.append(((r.get('status') == 'watching',
                           str(r.get('last_watched') or '')), sid))
        seen = set()
        for _score, sid in sorted(cands, key=lambda t: t[0], reverse=True):
            if sid in seen:
                continue
            seen.add(sid)
            d = ex.detail(sid) or {}
            det[sid] = d
            rel[sid] = d.get('relations') or []
            # every airing show needs its episode list, not the first 30:
            # the rest had no date and vanished from the 14-day feed
            if len(eps) < 60 and d.get('status') == 'airing':
                eps[sid] = ex.episodes(sid)
            if len(seen) >= 60:
                break
        return rel, eps, det

    # --- search -----------------------------------------------------------
    def search_for(self, q):
        q = str(q or '').strip()
        if not q:
            raise ValueError('need something to search for')
        with self.lock:
            if self.search.get('busy'):
                raise ValueError('a search is already running')
            self.search = {'q': q, 'results': self.search.get('results') or [],
                           'busy': True}
        threading.Thread(target=self._search_worker, args=(q,),
                         daemon=True).start()

    def _search_worker(self, q):
        try:
            items = self._finder(q) or []
        except Exception as ex:
            log.cprint(f'search: failed ({ex})')
            with self.lock:
                self.search = {'q': q, 'results': [], 'busy': False}
                self.message = f'search failed: {ex}'
            return
        with self.lock:
            self.search = {'q': q, 'busy': False, 'results': [
                {'title': str(r.get('title') or ''), 'source': r.get('source'),
                 'url': str(r.get('url') or ''), 'ids': r.get('ids') or {},
                 'matched': r.get('matched')} for r in items]}
            self.message = '' if items else f'no results for “{q}”'

    # --- open / play / stop -----------------------------------------------
    def open(self, src=None, target=None):
        target = str(target or '').strip()
        if not target:
            raise ValueError('need a link or a title to open')
        src = str(src or '').strip()
        if not src:
            from ..cli_all import route
            got = route(target)
            if got is None:
                raise ValueError('pick a source for this link')
            src, target = got
        if src not in SOURCES:
            raise ValueError(f'unknown source {src!r}')
        with self.lock:
            if self.loading:
                raise ValueError('a show is already loading')
            self.loading = True
            self.message = f'loading  {target} …'
        threading.Thread(target=self._open_worker, args=(src, target),
                         daemon=True).start()

    def _open_worker(self, src, target):
        try:
            session = self._loader(src, target)
        except Exception as ex:
            log.cprint(f'load: {src} {target} failed ({ex})')
            with self.lock:
                self.loading = False
                self.message = f'error: {ex}'
            return
        with self.lock:
            old, self.session, self.loading, self.message = (
                self.session, session, False, '')
        if old is not None:
            try:
                old.close()
            except Exception as ex:
                log.cprint(f'load: old session close failed ({ex})')

    def options(self, body) -> dict:
        """Normalize a form payload through the ONE shared options model."""
        opts, mpv = self._normalize(body)
        with self.lock:
            session = self.session
        return {'opts': opts, 'mpv': mpv,
                'fields': self._fields(session, opts, mpv)}

    def _normalize(self, body):
        fields = body.get('fields') or []
        opts = body.get('opts') or {}
        mpv = body.get('mpv') or []
        if fields:
            return form_result(fields, opts, mpv)
        po = PlaybackOptions(opts, mpv)
        return po.to_opts(), po.mpv()

    def play(self, body):
        chosen = []
        for v in body.get('eps') or []:
            try:
                chosen.append(int(v))
            except (TypeError, ValueError):
                raise ValueError(f'bad episode number {v!r}')
        if not chosen:
            raise ValueError('pick at least one episode')
        with self.lock:
            session = self.session
            if session is None:
                raise ValueError('no show is loaded')
            if self.playing:
                raise ValueError('already playing - stop first')
            self.playing = True
            self.message = 'starting…'
        opts, mpv = self._normalize(body)
        threading.Thread(target=self._play_worker,
                         args=(session, chosen, opts, mpv),
                         daemon=True).start()

    def _play_worker(self, session, chosen, opts, mpv):
        try:
            session.play(chosen, opts, mpv)
            self._say('')
        except Exception as ex:
            log.cprint(f'play: failed ({ex})')
            self._say(f'error: {ex}')
        finally:
            with self.lock:
                self.playing = False

    def stop(self):
        with self.lock:
            session = self.session
        if session is None:
            raise ValueError('nothing is playing')
        session.stop()
        with self.lock:
            self.message = 'stopped'

    def settings(self, rails):
        if not isinstance(rails, dict):
            raise ValueError('rails must be an object')
        try:
            out = save_rails(self.cfg, rails)
        except Exception as ex:
            raise ValueError(f'settings not saved: {ex}')
        with self.lock:
            self.rails = out
        self.refresh_library()
        return out

    # --- the snapshot -----------------------------------------------------
    def snapshot(self) -> dict:
        with self.lock:
            session = self.session
            view = self._session_view(session) if session else None
            raw = getattr(session, 'opts', None) or {}
            mpv = list(getattr(session, 'mpv', None) or [])
            opts = PlaybackOptions(raw, mpv).to_opts()
            return {
                'lights': dict(self.lights),
                'rails': {'continue': list(self.rails_items['continue']),
                          'recent': list(self.rails_items['recent'])},
                'feed': list(self.feed),
                'upcoming': list(self.upcoming),
                'history': list(self.history),
                'session': view,
                'search': dict(self.search),
                'opts': {'fields': self._fields(session, opts, mpv),
                         'opts': opts, 'mpv': mpv},
                'rails_settings': dict(self.rails),
                'status': {'message': self.message, 'loading': self.loading,
                           'playing': self.playing},
                'log': self.lines[-40:],
            }

    def _fields(self, session, opts, mpv):
        """Always render the panel: with no session the fields are defaults
        the UI shows disabled, so the slot never appears/disappears."""
        groups = [str(g.get('label')) for g in
                  (getattr(session, 'groups', None) or [])
                  if isinstance(g, dict) and g.get('label')]
        return form_fields(groups=groups,
                           audio=bool(session and session.src == 'axp'),
                           opts=opts, mpv=mpv)

    def _session_view(self, s) -> dict:
        labels = dict(getattr(s, 'labels', None) or {})
        try:
            status = s.status()
        except Exception as ex:
            log.cprint(f'web: session status failed ({ex})')
            status = 'idle'
        return {'src': s.src, 'title': s.title or '',
                'link': s.link or '', 'mal': getattr(s, 'mal_id', None),
                'episodes': [{'num': n, 'name': str(labels.get(n)
                                                    or f'Episode {n}')}
                             for n in sorted(labels)],
                'resume': (s.resume[0] if getattr(s, 'resume', None) else None),
                'playing': self.playing, 'status': status}


class Handler(BaseHTTPRequestHandler):
    """JSON API + the built bundle. Errors are JSON, never an HTML page."""

    server_version = 'tgplay-web'

    def log_message(self, *args):           # the app has its own log
        pass

    @property
    def state(self) -> AppState:
        return self.server.state

    def do_GET(self):
        self._route('GET')

    def do_POST(self):
        self._route('POST')

    def _route(self, method):
        path = urlparse(self.path).path
        try:
            if path == '/api/events':
                return self._sse()
            if method == 'GET':
                if path == '/api/state':
                    return self._json(self.state.snapshot())
                if path.startswith('/api/'):
                    return self._error(404, f'no endpoint {path}')
                return self._static(path)
            body = self._body()
            if path == '/api/search':
                self.state.search_for(body.get('q'))
            elif path == '/api/open':
                self.state.open(body.get('src'), body.get('url'))
            elif path == '/api/play':
                self.state.play(body)
            elif path == '/api/stop':
                self.state.stop()
            elif path == '/api/options':
                return self._json(self.state.options(body))
            elif path == '/api/settings':
                self.state.settings(body.get('rails'))
            else:
                return self._error(404, f'no endpoint {path}')
            self._json(self.state.snapshot())
        except ValueError as ex:            # a user mistake, not a bug
            self._error(400, str(ex))
        except (BrokenPipeError, ConnectionResetError):
            pass                        # the window closed mid-response
        except Exception as ex:
            log.cprint(f'web: {method} {path} failed ({ex})')
            self._error(500, str(ex))

    # --- plumbing ---------------------------------------------------------
    def _body(self) -> dict:
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b''
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode('utf-8', 'replace'))
        except ValueError:
            raise ValueError('request body is not JSON')
        if not isinstance(data, dict):
            raise ValueError('request body must be a JSON object')
        return data

    def _json(self, data, code: int = 200):
        raw = json.dumps(data, default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, code: int, msg: str):
        self._json({'error': msg}, code)

    def _static(self, path):
        if not os.path.isdir(DIST):
            return self._html(MISSING)
        rel = path.lstrip('/') or 'index.html'
        full = os.path.normpath(os.path.join(DIST, rel))
        if not full.startswith(DIST + os.sep) and full != DIST:
            return self._error(403, 'outside the bundle')
        if os.path.isdir(full):
            full = os.path.join(full, 'index.html')
        if not os.path.isfile(full):
            full = os.path.join(DIST, 'index.html')   # the app owns its routes
        with open(full, 'rb') as f:
            raw = f.read()
        self.send_response(200)
        self.send_header('Content-Type',
                         TYPES.get(os.path.splitext(full)[1], 'application/octet-stream'))
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _html(self, text: str, code: int = 200):
        raw = text.encode()
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self):
        """The log tail as one SSE burst; EventSource asks again in 2 s.

        Closing the response keeps no thread parked and keeps a headless
        screenshot (--virtual-time-budget) from waiting on an open stream -
        which is also why the UI shows the newest line instead of replaying.
        """
        with self.state.lock:
            lines = list(self.state.lines[-40:])
        raw = ('retry: 2000\n\n' + ''.join(
            f'data: {json.dumps({"line": line})}\n\n' for line in lines)
        ).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve(port: int = PORT, state: AppState = None) -> ThreadingHTTPServer:
    """Bind 127.0.0.1:`port` (0 = any free port) and start the workers."""
    server = ThreadingHTTPServer((HOST, port), Handler)
    server.daemon_threads = True
    server.state = state or default_state()
    server.state.start()
    return server


def default_state() -> AppState:
    if os.environ.get('TPLAY_FAKE') == '1':
        state = AppState(loader=FakeLoader(),
                         overview=FakeLibrary().overview,
                         probe=FakeLibrary.lights, extra=False)
        state.session, state.search = FakeSession(), {
            'q': 'renegade immortal', 'busy': False, 'results': FAKE_RESULTS}
        return state
    return AppState()


# --- fake backend (TPLAY_FAKE=1 and the tests) ----------------------------
class FakeSession:
    """A loaded show that plays nothing: the UI's shape without the network."""

    src = 'agp'

    def __init__(self):
        self.title = 'Renegade Immortal'
        self.link = 'https://animegate.ir/anime/xian-ni'
        self.mal_id = 51289
        self.groups = [{'label': '720p · x265'}, {'label': '1080p · x264'}]
        self.labels = {n: name for n, name in zip(range(158, 171), (
            'Restart REEMBODY', 'Full ME night cruise', 'Saturday night',
            'Natural enemy', 'Motivated people INDUCTANCE',
            'Potential heat source excavation', 'Rhapsody is the Tune',
            'The Fifth Layer', 'Nine Turns', 'Soul Refining',
            'Bloodline Awakening', 'Ancient Restriction', 'Sea of Stars'))}
        self.resume = (163, 0)
        self.opts = {'f': '720p · x265', 'skip': 'off', 'sync': 'auto'}
        self.mpv = []
        self.played = []

    def play(self, chosen, opts, mpv):
        self.played.append(list(chosen))

    def stop(self):
        self.stopped = True

    def close(self):
        pass

    def status(self):
        return 'ep 163   22:41'


class FakeLoader:
    """`loader(src, target) -> Session` stand-in that never opens anything."""

    def __call__(self, src, target):
        self.src, self.target = src, str(target)
        return FakeSession()


class FakeLibrary:
    """The rows `library.overview()` returns, with dates relative to today."""

    SHOWS = [
        ('The Exiled Heavy Knight Knows How to Grind', 1, 58, 'today'),
        ('A Will Eternal Final Season', 0, 34, '2d'),
        ('Shrouding the Heavens', 7, 100, '3d'),
        ('Renegade Immortal', 5, 172, '5d'),
        ('Tales of Herding Gods', 12, 12, '5d'),
        ("A Record of Mortal's Journey to Immortality", 3, 58, '6d'),
        ("Beyond Time's Gaze 2", 9, 42, '6d'),
        ('Jade Dynasty Final Season', 2, 29, '7d'),
        ('Bleach: TYBW - The Calamity', 4, 52, '10d'),
        ('Link Click', 3, 25, '14d'),
    ]

    @staticmethod
    def _date(days_ago: int) -> str:
        from datetime import date, timedelta
        return (date.today() - timedelta(days=days_ago)).isoformat()

    def overview(self) -> dict:
        rows = []
        for i, (title, watched, total, ago) in enumerate(self.SHOWS):
            days = 0 if ago == 'today' else int(ago.rstrip('d'))
            rows.append({'title': title, 'simkl': 1000 + i, 'mal': None,
                         'watched': watched, 'total': total,
                         'next_ep': watched + 1, 'status': 'watching',
                         'air_date': self._date(days),
                         'last_watched': self._date(days),
                         'poster': ''})
        return {'cal': [], 'rem': rows, 'rows': rows, 'hist': [
            {'title': t['title'], 'watched': t['watched'], 'total': t['total'],
             'last_watched': t['last_watched']} for t in rows[:4]]}

    @staticmethod
    def lights():
        return [{'key': 'simkl', 'state': 'ok'},
                {'key': 'gate', 'state': 'ok'},
                {'key': 'anilist', 'state': 'warn'}]


FAKE_RESULTS = [
    {'title': 'Renegade Immortal · ep 163', 'source': 'agp', 'matched': 'id',
     'url': 'https://animegate.ir/anime/xian-ni', 'ids': {'mal': 51289}},
    {'title': 'Xian Ni · ep 163', 'source': 'tgp', 'matched': 'name',
     'url': 'https://t.me/xianni/163', 'ids': {'mal': 51289}},
    {'title': 'Renegade Immortal S1', 'source': 'axp', 'matched': 'name',
     'url': 'axp:xian-ni-s1', 'ids': {}},
    {'title': 'Fanren Xiu Xian Chuan: Mulan', 'source': 'agp',
     'matched': 'maybe', 'url': 'https://animegate.ir/anime/mulan', 'ids': {}},
]


def main(argv=None) -> int:
    """`python -m tp.web.server` - serve without opening a window."""
    port = int(os.environ.get('TPLAY_WEB_PORT') or PORT)
    server = serve(port)
    print(f'tgplay web: http://{HOST}:{server.server_address[1]}/')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
