"""Scrobble: first-service policy, >=80% auto-mark, 20s lock pacing."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.simkl_sync import SyncQueue                               # noqa: E402
from tp.tracking.scrobble import ScrobbleSync                     # noqa: E402
from tp.tracking.watched import WatchedSync                       # noqa: E402
from tracking_fakes import Cfg, FakeAniList, FakeSimkl            # noqa: E402


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def rig(tmp, clock=None):
    cfg = Cfg(tmp)
    q = SyncQueue(cfg.simkl_queue)
    simkl = FakeSimkl()
    watched = WatchedSync(cfg, q, simkl, FakeAniList())
    return q, simkl, watched, ScrobbleSync(simkl, watched,
                                           clock=clock or Clock())


def test_start_and_pause_go_to_simkl(tmp_path):
    clock = Clock()
    _q, simkl, _w, sc = rig(tmp_path, clock)
    sc.send('start', {'simkl': 7}, 3, 0)
    clock.now += 30                     # past the 20s write lock
    sc.send('pause', {'simkl': 7}, 3, 40)
    assert [c[0] for c in simkl.calls] == ['scrobble', 'scrobble']


def test_stop_at_80_percent_marks_watched(tmp_path):
    _q, simkl, watched, sc = rig(tmp_path)
    sc.send('stop', {'simkl': 7}, 3, 92)
    assert watched.state('simkl:7')['eps'] == {3}
    assert len(_q) == 1                        # queued, not a second network hit


def test_stop_below_80_does_not_mark(tmp_path):
    _q, _s, watched, sc = rig(tmp_path)
    sc.send('stop', {'simkl': 7}, 3, 55)
    assert watched.state('simkl:7')['eps'] == set()


def test_20_second_lock_paces_the_next_write(tmp_path):
    clock = Clock()
    _q, simkl, _w, sc = rig(tmp_path, clock)
    sc.send('start', {'simkl': 7}, 3, 0)
    clock.now += 5
    assert sc.send('pause', {'simkl': 7}, 3, 20) == {'skipped': 'lock'}
    assert len(simkl.calls) == 1
    clock.now += 20
    sc.send('pause', {'simkl': 7}, 3, 30)
    assert len(simkl.calls) == 2


def test_logged_out_client_is_a_noop(tmp_path):
    _q, simkl, watched, sc = rig(tmp_path)
    simkl.logged_in = lambda: False
    assert sc.send('start', {'simkl': 7}, 3, 0) is None
    assert simkl.calls == []
