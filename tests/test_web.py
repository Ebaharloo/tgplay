"""tp.web.server - the M1 web API. No network, no browser, no Simkl.

Every test starts the real server on port 0 with stubbed library/session
seams (`AppState(loader=..., overview=...)`), so the JSON the window gets is
exactly what a fake run produces.
"""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from tp import log
from tp.config import Config, load_json
from tp.options import form_fields, form_result
from tp.web.server import AppState, FakeLibrary, FakeLoader, serve

RESULTS = [{'title': 'Renegade Immortal', 'source': 'agp', 'matched': 'id',
            'url': 'https://animegate.ir/anime/xian-ni', 'ids': {'mal': 51289}},
           {'title': 'Xian Ni', 'source': 'axp', 'matched': 'name',
            'url': 'axp:xian-ni', 'ids': {}}]


class Client:
    """urllib wrapper that hands back (status, json) instead of raising."""

    def __init__(self, base):
        self.base = base

    def _do(self, req):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as ex:
            return ex.code, json.loads(ex.read() or b'{}')

    def get(self, path):
        return self._do(self.base + path)

    def post(self, path, body=None):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body or {}).encode(),
            headers={'Content-Type': 'application/json'})
        return self._do(req)

    def state(self):
        return self.get('/api/state')[1]

    def wait(self, pick, tries=100):
        """Poll /api/state until pick(state) is truthy (workers are threads)."""
        for _ in range(tries):
            got = pick(self.state())
            if got:
                return got
            time.sleep(0.05)
        raise AssertionError('state never settled')


@pytest.fixture
def web(tmp_path):
    cfg = Config(home=str(tmp_path)).ensure()
    old_sink = log.SINK
    state = AppState(cfg=cfg, loader=FakeLoader(),
                     overview=FakeLibrary().overview,
                     probe=FakeLibrary.lights, extra=False,
                     finder=lambda q: list(RESULTS))
    server = serve(0, state)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield Client(f'http://127.0.0.1:{server.server_address[1]}'), cfg
    finally:
        server.shutdown()
        server.server_close()
        log.SINK = old_sink


def test_state_shape(web):
    client, _cfg = web
    code, snap = client.get('/api/state')
    assert code == 200
    for key in ('lights', 'rails', 'feed', 'history', 'session', 'search',
                'opts', 'rails_settings', 'status'):
        assert key in snap, key
    assert set(snap['lights']) == {'simkl', 'gate', 'anilist'}
    assert snap['session'] is None
    rails = snap['rails']
    assert rails['continue'] and rails['recent']
    card = rails['continue'][0]
    for key in ('title', 'next_ep', 'watched', 'total', 'pct', 'image'):
        assert key in card, key
    assert snap['feed'] and {'date', 'ep', 'title', 'days'} <= set(snap['feed'][0])
    assert snap['history'] and {'watched', 'prog', 'title'} <= set(snap['history'][0])
    # no session -> no quality row yet, but the shared option flags are there
    kinds = [f['k'] for f in snap['opts']['fields']]
    assert 'skip' in kinds and 'sync' in kinds


def test_search_returns_rows(web):
    client, _cfg = web
    code, _snap = client.post('/api/search', {'q': 'renegade immortal'})
    assert code == 200
    rows = client.wait(
        lambda s: not s['search']['busy'] and s['search']['results'])
    assert rows and all(r['source'] and r['url'] for r in rows)
    assert rows[0]['title'] == 'Renegade Immortal'
    assert client.post('/api/search', {'q': ''})[0] == 400


def test_open_play_stop_need_a_session(web):
    client, _cfg = web
    assert client.post('/api/play', {'eps': [1]})[0] == 400
    assert client.post('/api/stop')[0] == 400
    code, body = client.post('/api/open', {'url': ''})
    assert code == 400 and body['error']

    assert client.post('/api/open', {'src': 'agp',
                                     'url': 'https://animegate.ir/x'})[0] == 200
    session = client.wait(lambda s: s['session'])
    assert session['src'] == 'agp' and session['episodes']
    assert session['episodes'][0]['num'] and session['episodes'][0]['name']

    assert client.post('/api/play', {'eps': [158], 'opts': {}})[0] == 200
    client.wait(lambda s: not s['status']['playing'])
    assert client.post('/api/stop')[0] == 200


def test_options_roundtrip(web):
    client, _cfg = web
    fields = form_fields(opts={'skip': 'off', 'sync': 'auto'})
    for f in fields:
        if f['k'] == 'skip':
            f['i'] = f['choices'].index('names')
        if f['k'] == 'next':
            f['val'] = True
        if f['k'] == 'cut':
            f['val'] = '45'
    base = {'a': False, 'e': None, 'f': None, 'skip_toggle': False,
            'nowait': False}
    want_opts, want_mpv = form_result(fields, base, [])
    code, got = client.post('/api/options',
                            {'fields': fields, 'opts': base, 'mpv': []})
    assert code == 200
    assert got['opts'] == want_opts
    assert got['mpv'] == want_mpv
    assert got['opts']['skip'] == 'names' and got['opts']['next'] == 0.60
    assert got['opts']['cut'] == 45


def test_settings_land_in_ui_json(web):
    client, cfg = web
    rails = {'continue': {'limit': 4}, 'recent': {'days': 30, 'limit': 8},
             'sidebar': {'days': 30, 'show_days': False}}
    assert client.post('/api/settings', {'rails': rails})[0] == 200
    saved = load_json(cfg.ui)['window']['rails']
    assert saved['recent']['days'] == 30
    assert saved['continue']['limit'] == 4
    assert client.state()['rails_settings']['recent']['days'] == 30
    # out-of-range values are clamped, not stored
    client.post('/api/settings', {'rails': {'recent': {'days': 3}}})
    assert load_json(cfg.ui)['window']['rails']['recent']['days'] == 14


def test_sse_streams_a_log_line(web):
    client, _cfg = web
    log.cprint('web-sse-probe line')
    with urllib.request.urlopen(client.base + '/api/events', timeout=10) as r:
        assert 'text/event-stream' in r.headers['Content-Type']
        body = r.read().decode()
    assert 'web-sse-probe line' in body
    assert any(json.loads(chunk[len('data: '):])['line'] == 'web-sse-probe line'
               for chunk in body.split('\n\n')
               if chunk.startswith('data: '))


def test_options_fields_exist_without_session(web):
    """The settings panel must render before a show is picked (was blank)."""
    client, _cfg = web
    snap = client.state()
    assert snap['session'] is None
    keys = [f['k'] for f in snap['opts']['fields']]
    assert len(keys) >= 6, keys
    assert 'skip' in keys and 'extra' in keys
    assert 'quality' not in keys, 'no groups -> no server picker'


def test_feed_is_aired_rows_not_rail_items(web):
    """Aired rows feed the sidebar even when the rail filters them out."""
    client, cfg = web

    class OffRail(FakeLibrary):
        def overview(self, *a, **k):
            ov = dict(super().overview(*a, **k))
            rows = []
            for r in ov.get('rows') or []:
                r = dict(r, watched=0, status='completed', last_watched='')
                rows.append(r)
            ov['rows'] = rows
            ov['rem'] = []
            return ov

    state = AppState(cfg=cfg, loader=FakeLoader(),
                     overview=OffRail().overview, probe=FakeLibrary.lights,
                     extra=False, finder=lambda q: list(RESULTS))
    server = serve(0, state)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        c = Client(f'http://127.0.0.1:{server.server_address[1]}')
        snap = c.wait(lambda s: s if s['feed'] else None)
        assert snap['rails']['recent'] == [], 'precondition: rail is empty'
        row = snap['feed'][0]
        assert set(row) >= {'date', 'days', 'ep', 'title'}
        assert 'upcoming' in snap
    finally:
        server.shutdown()
        server.server_close()
