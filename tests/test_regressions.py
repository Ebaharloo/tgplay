#!/usr/bin/env python3
"""test_regressions - one test per dev-pass fix; each FAILS if it is unwired.

Claims 1-12 from TEST-GATE-2026-11-05.md. No network, no mpv, no proxy:
the player, provider, skip service and PosWatcher are all stubs.
Run: env -u PYTHONPATH .venv/bin/python -m pytest tests/test_regressions.py -q
"""
import json
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['AGP_NO_TRACK'] = '1'          # no tracker threads in these tests

import pytest  # noqa: E402

from tp import options  # noqa: E402
from tp import playlist as playlist_mod  # noqa: E402
from tp.config import Config  # noqa: E402
from tp.episodes import Episode  # noqa: E402
from tp.playlist import Playlist  # noqa: E402

SKIP_FLAGS = ['--script-opts=skip-op_start=90.0,skip-op_end=120.0']
HLS = 'https://cdn.example/x/master.m3u8'


# --- stubs (mirror the ui_coverage_audit harness) -------------------------
class Stream:
    def __init__(self, url=HLS, headers=None, direct=True, subs=()):
        self.url = url
        self.headers = {'Referer': 'https://animex.one/'} if headers is None \
            else dict(headers)
        self.direct = direct
        self.subs = list(subs)


class FakeProvider:
    title = 'One Piece'
    # axp fakes carry the real AnimeX Audio object (play applies it)
    from tp.features.audio import AxpAudio as _A
    from tp.features.servers import AxpServers as _S
    audio = _A()
    servers = _S()
    from tp.features.warm import MirrorWarm as _W
    warm = _W()
    from tp.features.auth import AxpAuth as _AU
    auth = _AU()

    def __init__(self, nums=(1, 2, 3)):
        self.nums = list(nums)
        self.order = []

    def episodes(self):
        return {n: f'Ep {n}' for n in self.nums}

    def stream(self, _n):
        return Stream()

    def display_name(self, n):
        return f'One Piece - {n}.mkv'

    def set_audio(self, a):
        self.order.append(('set_audio', a))

    def select(self, q):
        self.order.append(('select', q))


class FakePlayer:
    def __init__(self, rc=0):
        self.rc = rc
        self.cmds = []
        self.stops = 0

    def command(self, url, *, title=None, extra=None, start=None, cut=None,
                end=None, ipc=None):
        return [url] + list(extra or [])

    def play(self, cmd):
        self.cmds.append(list(cmd))
        return self.rc

    def stop(self):
        self.stops += 1


class FakeSkip:
    def __init__(self, flags=SKIP_FLAGS):
        self.out = list(flags)
        self.calls = []

    def flags(self, **kw):
        self.calls.append(kw)
        return list(self.out), 'fake'


class FakeWatcher:
    """PosWatcher without the socket: no mpv IPC, no 12 s joins."""
    duration = 0
    last = 0

    def __init__(self, *a, **k):
        self.kw = k

    def start(self):
        pass

    def join(self, timeout=None):
        pass


@pytest.fixture(autouse=True)
def _no_watcher(monkeypatch):
    monkeypatch.setattr(playlist_mod, 'PosWatcher', FakeWatcher)


@pytest.fixture
def cfg(tmp_path):
    return Config(home=str(tmp_path)).ensure()


def _run(cfg, prov, player, skip=None, mal_id=None, nums=None, **kw):
    pin = {} if mal_id is None else {'mal_id': mal_id}
    pl = Playlist(prov, None, None, player, cfg, skip=skip, **pin)
    eps = [Episode(n, f'l{n}') for n in (nums or prov.nums)]
    pl.run(eps, **kw)
    return pl


def _session(cfg, prov, src='axp', opts=None):
    from tp.session import Session
    s = Session(src, prov, cfg, None, None, None,
                groups=[{'label': 'x'}], labels=prov.episodes(), resume=None,
                opts=dict(opts or {}), mpv=[], audio=True, link=None)
    s._player = FakePlayer()
    s._proxy = types.SimpleNamespace()     # direct streams never touch it
    return s


# --- 1. skip flags reach mpv for DIRECT (HLS) streams ---------------------
def test_claim1_direct_stream_is_probed_with_its_headers(cfg):
    prov, player, skip = FakeProvider(), FakePlayer(), FakeSkip()
    _run(cfg, prov, player, skip=skip, skip_mode='all')

    call = skip.calls[0]
    # the exact URL mpv plays, with its headers, and nothing else to try
    assert call['targets'] == [(HLS, {'Referer': 'https://animex.one/'})], call

    cmd = player.cmds[0]
    assert any(a.startswith('--script-opts=skip-op_start=90') for a in cmd), cmd


# --- 2. the session's pinned mal_id reaches ani-skip ----------------------
def test_claim2_pinned_mal_id_is_used_when_provider_has_none(cfg):
    prov = FakeProvider()
    assert not hasattr(prov, 'mal_id')       # provider cannot supply one
    skip = FakeSkip(flags=[])
    _run(cfg, prov, FakePlayer(), skip=skip, mal_id=4242)
    assert skip.calls[0]['mal_id'] == 4242, skip.calls[0]


# --- 3. atomic JSON writes ------------------------------------------------
def test_claim3_save_json_keeps_old_file_when_replace_fails(tmp_path,
                                                            monkeypatch):
    from tp.config import save_json           # the fix itself (absent = red)
    p = str(tmp_path / 'cfg.json')
    save_json(p, {'keep': 1})

    def boom(*_a, **_k):
        raise OSError('crash between write and replace')

    monkeypatch.setattr(os, 'replace', boom)
    with pytest.raises(OSError):
        save_json(p, {'keep': 2})
    assert json.load(open(p)) == {'keep': 1}


# --- 4. AnimeX: audio is set BEFORE the server is selected -----------------
def test_claim4_animex_set_audio_before_select(cfg):
    prov = FakeProvider(nums=(1, 2))
    prov.set_audio = lambda a: prov.order.append(('set_audio', a))
    prov.select = lambda q: prov.order.append(('select', q))
    s = _session(cfg, prov, src='axp')
    s._skip = FakeSkip(flags=[])
    s.play([1], {'audio': 'sub', 'f': 'yuki  (dub)'}, [])

    assert prov.order[:2] == [('set_audio', 'sub'),
                              ('select', 'yuki  (dub)')], prov.order


# --- 5. mpv failing to start stops the playlist ---------------------------
def test_claim5_player_start_failure_ends_the_run(cfg):
    prov, player = FakeProvider(nums=(1, 2, 3)), FakePlayer(rc=1)
    _run(cfg, prov, player, skip=FakeSkip(flags=[]))
    assert len(player.cmds) == 1, player.cmds        # not 3 'finished' episodes
    prog = {}
    if os.path.exists(cfg.progress):
        prog = json.load(open(cfg.progress))
    assert 'One Piece' not in prog, prog             # nothing marked watched


# --- 11. skip 'off' is off end-to-end; unset False still means 'all' ------
def test_claim11_skip_off_means_off_and_false_means_all(cfg):
    from tp.skip import SkipService

    class Reader:
        def read(self, url, headers=None, timeout=None):
            return [('Intro', 0.0, 90.0), ('Episode', 90.0, 1300.0)]

    def run(skip_opt):
        prov = FakeProvider(nums=(1,))
        s = _session(cfg, prov, src='agp')
        s._skip = SkipService(reader=Reader(), ani_skip=None, metadata=None)
        s.play([1], {'skip': skip_opt}, [])
        return s._player.cmds[0]

    # PlaybackOptions keeps an explicit 'off' as a real choice
    assert options.PlaybackOptions({'skip': 'off'}).to_opts()['skip'] == 'off'
    cmd_off = run('off')
    assert not any('--script-opts' in a for a in cmd_off), cmd_off
    # legacy unset False still means 'all'
    cmd_all = run(False)
    assert any(a.startswith('--script-opts=skip-op_start') for a in cmd_all), \
        cmd_all

    # and the session passes the mode down verbatim
    skip = FakeSkip(flags=[])
    s = _session(cfg, FakeProvider(nums=(1,)), src='agp')
    s._skip = skip
    s.play([1], {'skip': 'off'}, [])
    assert skip.calls[0]['mode'] == 'off', skip.calls[0]


# --- 13. a failed 2 s head peek must not kill skip on proxy streams -------
class SlowProxy:
    """prewarm never signals: the head peek times out, like a slow CDN."""

    def __init__(self):
        self.registered = []

    def register(self, name, stream):
        self.registered.append((name, stream))

    def prewarm(self, name, ev):
        pass

    def url(self, name):
        return f'http://127.0.0.1:9/{name}'


class ProxyProvider(FakeProvider):
    def stream(self, n):
        return Stream(url=f'https://cdn.example/x/{n}.mkv', direct=False)


def test_claim13_failed_head_peek_still_yields_skip_flags(cfg):
    prov, player, skip = ProxyProvider(nums=(1,)), FakePlayer(), FakeSkip()
    Playlist(prov, SlowProxy(), None, player, cfg, skip=skip).run(
        [Episode(1, 'l1')], skip_mode='all')

    targets = skip.calls[0]['targets']
    assert targets[0][0] == 'https://cdn.example/x/1.mkv', targets   # origin
    assert targets[1][0].startswith('http://127.0.0.1:9/'), targets  # proxy
    cmd = player.cmds[0]
    assert any(a.startswith('--script-opts=skip-op_start=90') for a in cmd), cmd


# --- 14. warm path and main loop both go through probe_targets ------------
def test_claim14_warm_and_main_paths_share_probe_targets(cfg, monkeypatch):
    seen = []
    real = playlist_mod.probe_targets

    def spy(stream, proxy_url=None):
        out = real(stream, proxy_url)
        seen.append(out)
        return out

    monkeypatch.setattr(playlist_mod, 'probe_targets', spy)
    prov, skip = ProxyProvider(nums=(1, 2)), FakeSkip(flags=[])
    pref = types.SimpleNamespace(prefetch=lambda name, st: None)
    pl = Playlist(prov, SlowProxy(), None, FakePlayer(), cfg, skip=skip,
                  prefetcher=pref)
    pl._skip_mode, pl._skip_toggle = 'all', False
    pl._warm(Episode(2, 'l2'))                    # warm path
    pl.run([Episode(1, 'l1')], skip_mode='all')   # main loop

    assert len(seen) == 2, seen
    assert seen[0][0][0] == 'https://cdn.example/x/2.mkv', seen[0]
    assert seen[1][0][0] == 'https://cdn.example/x/1.mkv', seen[1]
    for t in seen:                                # origin, then our proxy
        assert len(t) == 2 and t[1][0].startswith('http://127.0.0.1:9/'), t


# --- GUI stubs ------------------------------------------------------------
class FakeSession:
    def __init__(self, title='One Piece', n=3):
        self.title = title
        self.groups = [{'label': '720p'}, {'label': '1080p'}]
        self.labels = {i: f'Episode {i}' for i in range(1, n + 1)}
        self.resume = None
        self.src = 'agp'
        self.opts = {'skip': False, 'f': '720p'}
        self.mpv = []
        self.audio = False
        self.link = 'https://animegate.ir/watch/one-piece-1074'
        self.calls = []

    def play(self, c, o, m):
        self.calls.append('play')

    def stop(self):
        self.calls.append('stop')

    def close(self):
        self.calls.append('close')

    def status(self):
        return 'ep 1   00:00'


@pytest.fixture
def win(monkeypatch, tmp_path):
    from tp import gui_all as GA
    from tp import log as tp_log
    from tp.gui_qt import _app
    app = _app()
    monkeypatch.setattr(GA.MainWindow, 'load_side', lambda self: None)
    w = GA.MainWindow(lambda src, target: None,
                      cfg=Config(home=str(tmp_path)).ensure())
    yield w
    for t in (w.debounce, w.poll, w.log_timer, w.st_timer, w.side_timer):
        t.stop()
    tp_log.SINK = w._prev_sink
    w.hide()
    w.deleteLater()
    app.processEvents()


# --- 7. play buttons follow the session ----------------------------------
def test_claim7_play_buttons_need_a_session(win):
    # the three play buttons moved into the episode table's context menu;
    # the bar keeps Stop, which still needs a session
    assert not win.b_stop.isEnabled()
    win.set_session(FakeSession())
    assert win.b_stop.isEnabled()
    assert not hasattr(win, 'b_from')


# --- 8. zero hits say so; Enter searches instead of loading row 0 ---------
def test_claim8_empty_results_are_explained(win, monkeypatch):
    win.box.setText('zzzznothing')
    loaded = []
    monkeypatch.setattr(win, 'load_target', lambda *a: loaded.append(a))

    win._fill_results([])
    assert 'no hits' in win.list_head.text().lower(), win.list_head.text()
    assert win.state['msg'].startswith('no results'), win.state['msg']

    win.state['msg'] = ''
    win._accept_typed()                      # Enter with an empty list
    assert not loaded, loaded                # did not load row 0
    assert win.debounce.isActive(), 'Enter must start a search'
    assert win.state['msg'].startswith('searching'), win.state['msg']
    win.debounce.stop()


# --- 9. the history picker keeps one row per link ------------------------
def test_claim9_history_keeps_one_row_per_link(win):
    from tp import history
    history.add(win._cfg, link='https://animegate.ir/watch/one-piece-1074',
                name='One Piece')
    history.add(win._cfg, link='axp:one-piece', name='One Piece')
    rows = win._hist_rows()
    assert len(rows) == 2, rows
    assert {r['url'] for r in rows} == {
        'https://animegate.ir/watch/one-piece-1074', 'axp:one-piece'}, rows


# --- 10. quoted extra mpv flags stay one argv entry -----------------------
def test_claim10_qt_form_keeps_quoted_flags_together(win):
    from tp import gui_all as GA
    form = GA.OptionsForm()
    form.load(None)
    form.extra.setText('--title="One Piece" --volume 80')
    _o, mpv = form.to_raw(FakeSession())
    assert mpv == ['--title=One Piece', '--volume', '80'], mpv

def test_claim10_shared_form_result_keeps_quoted_flags_together():
    fields = options.form_fields(groups=['720p'])
    for f in fields:
        if f['k'] == 'extra':
            f['val'] = '--title="One Piece" --volume 80'
    _o, mpv = options.form_result(fields, {}, [])
    assert mpv == ['--title=One Piece', '--volume', '80'], mpv


# --- 12. Stop with no session, and the message expires -------------------
def test_claim12_stop_message_and_expiry(win):
    win.state['session'] = None
    win._do_stop()
    assert win.state['msg'] == 'nothing playing', win.state['msg']
    assert win.state['msg_until'] > time.time(), win.state.get('msg_until')

    win.state['msg'] = 'stopped'
    win.state['msg_until'] = time.time() - 1
    win._refresh_status()
    assert win.state['msg'] == '', win.state
    assert win.status.text() == 'idle', win.status.text()


# --- 6. close during playback stops the session before closing ----------
def test_claim6_close_stops_the_session_first(win):
    sess = FakeSession()
    win.set_session(sess)
    win.close_window()
    assert sess.calls == ['stop', 'close'], sess.calls


# --- 13. Stop ends the whole playlist, it is not a per-episode pause -----
def test_claim13_stop_ends_the_playlist():
    import threading

    from tp import playlist as P

    class Watch:
        duration, last = 100, 10
        def __init__(self, *a, **k): pass
        def start(self): pass
        def join(self, timeout=None): pass
    P.PosWatcher = Watch

    class Stream:
        direct = True; url = 'file:///tmp/x.mkv'; headers = {}; subs = []
    class Prov:
        title = 'T'; mal_id = None
        def stream(self, n): return Stream()
    plays = []
    class Player:
        def command(self, url, **k): return [url]
        def play(self, cmd):
            plays.append(cmd)
            stop.set()                 # user hits Stop while ep 1 plays
            return 4
    class Cfg: progress = '/tmp/p.json'
    class Cache: pass

    stop = threading.Event()
    pl = P.Playlist(Prov(), None, Cache(), Player(), Cfg(), stop=stop)
    pl._save = lambda *a, **k: None
    out = pl.run([P.Episode(i, f'E{i}') for i in (1, 2, 3)])
    assert out == 'stopped', out
    assert len(plays) == 1, f'playlist kept going: {len(plays)} episodes'


# --- 14. the sidebar width survives a restart ----------------------------
def test_claim14_sidebar_width_is_remembered(win, tmp_path):
    import json
    from tp import gui_all as GA
    from tp.config import Config
    from tp.gui_qt import _app as _qapp

    win.show()
    win._split_h.setSizes([700, 520])
    win._remember_window_state()
    saved = json.load(open(Config(home=str(tmp_path)).ui))['window']['split']
    assert saved[1] > 240, saved                    # not just the minimum

    again = GA.MainWindow(lambda src, target: None, cfg=Config(home=str(tmp_path)))
    again.show()
    _qapp().processEvents()
    try:
        got = again._split_h.sizes()
        assert abs(got[1] / sum(got) - saved[1] / sum(saved)) < 0.02, (got, saved)
    finally:
        for t in (again.debounce, again.poll, again.log_timer, again.st_timer,
                  again.side_timer, again._sz_timer):
            t.stop()
        again.hide()


# --- 15. an airing show has NO last_aired, so the episode list decides -----
def test_claim15_airing_show_uses_episode_list_not_last_aired():
    from datetime import date, timedelta
    from tp.recent import RecentlyAired

    today = date.today()
    rows = [{'title': 'Renegade Immortal', 'simkl': 42, 'status': 'watching',
             'watched': 160, 'total': 172, 'next_ep': 161, 'last_watched': '',
             'air_date': None}]          # exactly what the live API returns
    # last_aired is None while a show is airing; the episode list has the date
    detail = {42: {'status': 'airing', 'last_aired': None}}
    eps = {42: [{'episode': 163, 'aired': True,
                 'date': (today - timedelta(days=2)).isoformat() + 'T00:00:00Z'}]}
    items = RecentlyAired(None).items(
        [dict(r, air_date=(eps[42][0]['date'])) for r in rows],
        days=14, relations={}, episodes=eps)
    assert items, 'airing show with a fresh episode must appear'
    assert items[0]['days_ago'] == 2, items[0]
    assert items[0]['behind'] == 3, items[0]      # 163 aired, 160 watched


# --- 16. concurrent cache writes must not lose each other ----------------
def test_claim16_concurrent_save_json_never_races(tmp_path):
    import threading
    from tp.config import save_json, load_json

    path = str(tmp_path / 'relations.json')
    errs = []

    def writer(n):
        try:
            for i in range(40):
                save_json(path, {f'k{n}': i})
        except Exception as ex:                  # the ENOENT rename race
            errs.append(ex)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errs, errs
    got = load_json(path)
    assert isinstance(got, dict) and got, got


# --- 13. finish-at: unusable pair is dropped, prefetch trigger uses it -----
def test_claim17_finish_at_before_start_is_ignored(cfg):
    """Start at 600 + Finish at 90 would make mpv exit at once: drop the end."""
    plays = []
    class Player:
        def command(self, url, **k):
            return [url, json.dumps(k, default=str)]
        def play(self, cmd):
            plays.append(json.loads(cmd[1]))
            return 0
    _run(cfg, FakeProvider(), Player(), start=600, end=90)
    assert plays, plays
    assert plays[0]['end'] is None, plays[0]
    assert plays[0]['start'] == 600, plays[0]


def test_claim18_next_ep_trigger_honours_finish_at():
    """Finish-at shortens the stream, so the 60% trigger must move with it."""
    pl = Playlist.__new__(Playlist)              # _trigger is pure
    fire = pl._trigger(None, 0.6, end=600)
    assert fire(300, 1440) is False, 'fired against the full 1440s duration'
    assert fire(400, 1440) is True, 'trigger ignored the 600s finish'
    cutfire = pl._trigger(None, 'cut', end=600)
    assert cutfire(300, 1440) is False and cutfire(560, 1440) is True


# --- 14. Start-at fallback when mpv drops --start -------------------------
def test_claim19_start_at_seek_fallback():
    from tp.player import ipc_seek
    from tp.playlist import _behind
    assert _behind(3, 180) is True            # opened at the top
    assert _behind(175, 180) is False         # --start worked
    assert _behind(0, None) is False          # nothing was asked
    assert _behind(0, 10) is False            # too small to bother
    assert ipc_seek('/tmp/no-such-mpv.sock', 180) is False   # no mpv: no raise


def test_claim20_options_panel_has_samples_and_help():
    from tp.gui_all import OptionsForm
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    f = OptionsForm()
    flags = [fl for _l, fl in f.SAMPLES]
    assert any('--volume' in x for x in flags), flags
    assert f.extra.text() == ''
    f._add_flag('--volume 80')
    f._add_flag('--volume 80')               # twice is a no-op
    assert f.extra.text() == '--volume 80', f.extra.text()
    f._add_flag('--no-border')
    assert f.extra.text() == '--volume 80 --no-border', f.extra.text()
    assert f.samples.menu() and len(f.samples.menu().actions()) == len(flags)
    assert f.help_btn.width() > 0 and f.start_at.placeholderText()
