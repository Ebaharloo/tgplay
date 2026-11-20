"""Ratings: same durable queue as watched; read/unrate wired, not dead."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest                                                     # noqa: E402

from tp.simkl_sync import SimklPusher, SyncQueue, Syncer           # noqa: E402
from tp.tracking.ratings import RatingSync                        # noqa: E402
from tracking_fakes import Cfg, FakeSimkl                         # noqa: E402


def rig(tmp):
    cfg = Cfg(tmp)
    q = SyncQueue(cfg.simkl_queue)
    simkl = FakeSimkl()
    return q, simkl, RatingSync(q, simkl)


def test_rate_is_queued_then_pushed_once(tmp_path):
    q, simkl, svc = rig(tmp_path)
    assert svc.rate({'simkl': 7}, 9) is True
    assert simkl.calls == []                      # queue first
    Syncer(q, pushers={'simkl': SimklPusher(simkl)}).flush()
    assert simkl.calls == [('rate', ({'simkl': 7}, 9))]


def test_out_of_range_and_no_ids_are_refused(tmp_path):
    _q, _s, svc = rig(tmp_path)
    with pytest.raises(ValueError):
        svc.rate({'simkl': 7}, 11)
    assert svc.rate({}, 9) is False


def test_unrate_and_read_reach_the_client(tmp_path):
    _q, simkl, svc = rig(tmp_path)
    assert svc.unrate({'simkl': 7}) is True
    assert svc.read() == [{'simkl': 1, 'user_rating': 9}]
    assert simkl.calls[-1] == ('ratings', (None,))
