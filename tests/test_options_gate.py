#!/usr/bin/env python3
"""test_options_gate - adversarial gate for 896af7f (start-at / finish-at).

Independent of the dev's own tests: each case tries to break one bullet of the
feature (position parsing, opts dict, mpv argv, form spec, playlist scoping,
Qt widgets, remembered setup). No network, no mpv, no proxy.
Run: env -u PYTHONPATH .venv/bin/python -m pytest tests/test_options_gate.py -q
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['AGP_NO_TRACK'] = '1'

import pytest  # noqa: E402

from tp import options  # noqa: E402
from tp import playlist as playlist_mod  # noqa: E402
from tp import setup  # noqa: E402
from tp.config import Config  # noqa: E402
from tp.episodes import Episode  # noqa: E402
from tp.options import (PlaybackOptions, form_fields, form_result,  # noqa: E402
                        _norm_pos)
from tp.player import Player  # noqa: E402
from tp.playlist import Playlist  # noqa: E402

HLS = 'https://cdn.example/x/master.m3u8'


# --- stubs ----------------------------------------------------------------
class Stream:
    url = HLS
    headers = {'Referer': 'https://animex.one/'}
    direct = True
    subs = ()


class FakeProvider:
    title = 'One Piece'

    def __init__(self, nums=(1, 2, 3)):
        self.nums = list(nums)

    def episodes(self):
        return {n: f'Ep {n}' for n in self.nums}

    def stream(self, _n):
        return Stream()

    def display_name(self, n):
        return f'One Piece - {n}.mkv'


class RecPlayer:
    """Records the kwargs Playlist hands to player.command()."""

    def __init__(self):
        self.calls = []

    def command(self, url, *, title=None, extra=None, start=None, cut=None,
                end=None, ipc=None):
        self.calls.append({'start': start, 'cut': cut, 'end': end})
        return [url]

    def play(self, cmd):
        return 0

    def stop(self):
        pass


class FakeWatcher:
    duration = 0

    def __init__(self, *a, **k):
        pass

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


# --- a) _norm_pos ---------------------------------------------------------
def test_norm_pos_forms_and_blanks():
    assert _norm_pos('90') == _norm_pos('1:30') == _norm_pos('0:01:30') == 90
    assert _norm_pos(90) == 90
    for blank in ('', None, '  ', ' \t '):
        assert _norm_pos(blank) is None, blank
    assert _norm_pos('abc') is None          # garbage: None, no exception
    for bad in ('1:2:3:4', '-30', '1:-30'):
        v = _norm_pos(bad)
        assert v is None or v >= 0, (bad, v)


@pytest.mark.xfail(reason='tp/options.py:87 int(inf) raises OverflowError - '
                          'typing "inf" in the Start at box crashes the form',
                   raises=OverflowError, strict=False)
def test_norm_pos_infinity_does_not_raise():
    assert _norm_pos('inf') is None
    assert _norm_pos('1e400') is None


# --- b) opts dict round-trip ---------------------------------------------
def test_opts_roundtrip_and_legacy_raw_dict():
    po = PlaybackOptions({'start': '1:30', 'end': '10:00'})
    o = po.to_opts()
    assert o['start'] == 90 and o['end'] == 600, o
    again = PlaybackOptions(o)
    assert again.start == 90 and again.end == 600
    assert again.to_opts()['start'] == 90
    # legacy callers hand a raw dict straight to the session
    raw = {'cut': 30, 'end': 600}
    cmd = Player().command('u', cut=raw['cut'], end=PlaybackOptions(raw).end)
    assert '--end=600' in cmd, cmd


# --- c) mpv argv rules ---------------------------------------------------
def test_mpv_end_rules():
    p = Player()
    cmd = p.command('u', start=10, cut=30, end=900)
    assert cmd.count('--end=900') == 1, cmd
    assert sum(f.startswith('--end') for f in cmd) == 1, cmd
    assert '--end=-30' not in cmd, cmd                 # absolute beats cut
    assert '--start=10' in cmd, cmd
    # end blank, cut set -> relative end only
    cmd = p.command('u', cut=30)
    assert cmd.count('--end=-30') == 1, cmd
    # both blank -> no --end at all
    cmd = p.command('u')
    assert not [f for f in cmd if f.startswith('--end')], cmd
    # explicit extras win, generated ones suppressed
    cmd = p.command('u', start=10, cut=30, end=99, extra=['--end=-5'])
    assert sum(f.startswith('--end') for f in cmd) == 1, cmd
    cmd = p.command('u', start=10, end=99, extra=['--start=3'])
    assert sum(f.startswith('--start') for f in cmd) == 1, cmd
    assert '--start=3' in cmd, cmd
    # start=0 is a real position (mpv accepts --start=0)
    assert '--start=0' in p.command('u', start=0)


# --- d) form spec --------------------------------------------------------
def test_form_fields_and_result_roundtrip():
    fields = form_fields(opts={'start': '1:30', 'end': 600, 'cut': 30})
    ks = [f['k'] for f in fields]
    assert ks.count('start') == 1 and ks.count('end') == 1, ks
    assert ks.index('start') < ks.index('end') < ks.index('cut'), ks
    by = {f['k']: f for f in fields}
    assert by['start']['kind'] == by['end']['kind'] == 'text', by
    assert by['start']['val'] == '90' and by['end']['val'] == '600', by
    o, _ = form_result(fields, {})
    assert o['start'] == 90 and o['end'] == 600 and o['cut'] == 30, o
    # blank clears, garbage clears instead of raising
    by['start']['val'] = '  '
    by['end']['val'] = 'xx'
    o, _ = form_result(fields, {})
    assert o['start'] is None and o['end'] is None, o
    assert o['cut'] == 30, o                        # neighbours untouched


# --- e) playlist scoping -------------------------------------------------
def test_playlist_end_first_episode_only(cfg):
    prov, player = FakeProvider(nums=(1, 2, 3)), RecPlayer()
    pl = Playlist(prov, None, None, player, cfg, skip=None)
    pl.run([Episode(n, f'l{n}') for n in (1, 2, 3)], cut=30, start=90, end=600)
    assert len(player.calls) == 3, player.calls
    assert player.calls[0]['end'] == 600, player.calls
    assert all(c['end'] is None for c in player.calls[1:]), player.calls
    assert all(c['cut'] == 30 for c in player.calls), player.calls
    assert player.calls[0]['start'] == 90, player.calls
    assert all(c['start'] is None for c in player.calls[1:]), player.calls


# --- f) Qt form (offscreen) ---------------------------------------------
def _session_like(opts, audio=False):
    return types.SimpleNamespace(
        opts=opts, mpv=[], audio=audio,
        groups=[{'label': '1080p'}], labels={1: 'Ep 1'})


def test_qt_form_shows_and_reads_positions():
    from tp.gui_all import OptionsForm
    from PySide6 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    f = OptionsForm()
    f.load(_session_like({'start': 90, 'end': 600, 'skip': 'names'}))
    assert f.start_at.text() == '90', f.start_at.text()
    assert f.finish_at.text() == '600', f.finish_at.text()
    o, _ = f.to_raw(_session_like({'start': 90, 'end': 600}))
    assert o['start'] == 90 and o['end'] == 600, o
    # blanking the boxes must clear the values, not keep the old ones
    f.start_at.setText('  ')
    f.finish_at.setText('')
    o, _ = f.to_raw(_session_like({'start': 90, 'end': 600}))
    assert o['start'] is None and o['end'] is None, o
    # the options box must fit its widest row (the user's clipping complaint)
    assert f.box.minimumWidth() >= 500, f.box.minimumWidth()
    lay = f.box.layout()
    for i in range(lay.count()):
        row = lay.itemAt(i).layout()
        if row is not None:
            assert f.box.minimumWidth() >= row.minimumSize().width(), \
                (i, row.minimumSize().width(), f.box.minimumWidth())
    # four rows: height covers every row, not just the old three
    one_row = f.server.sizeHint().height()
    assert f.box.sizeHint().height() >= 4 * one_row, \
        (f.box.sizeHint().height(), one_row)
    del app
    f.deleteLater()


# --- g) remembered setup -------------------------------------------------
def test_start_end_are_not_persisted_by_design(tmp_path):
    """Dev says start/end are intentionally per-show, never remembered."""
    saved = PlaybackOptions({'start': 90, 'end': 600, 'cut': 30}).saved_shape()
    assert 'start' not in saved and 'end' not in saved, saved
    p = str(tmp_path / 'ui.json')
    setup.save(p, {'start': 90, 'end': 600}, [], 'agp')
    o, _ = setup.apply({}, [], setup.load(p))
    assert 'start' not in setup.load(p), setup.load(p)
    assert o.get('start') is None and o.get('end') is None, o
    # cut still round-trips, so this is specific to the new keys
    setup.save(p, {'cut': 30}, [], 'agp')
    assert setup.apply({}, [], setup.load(p))[0]['cut'] == 30
