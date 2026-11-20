"""List status: Simkl native + the AniList status map (no hardcoded CURRENT)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest                                                     # noqa: E402

from tp.simkl_sync import SyncQueue                               # noqa: E402
from tp.tracking.lists import ListStatusSync                      # noqa: E402
from tracking_fakes import Cfg, FakeAniList, FakeSimkl            # noqa: E402


def test_simkl_list_status_is_queued_not_fired(tmp_path):
    cfg = Cfg(tmp_path)
    q = SyncQueue(cfg.simkl_queue)
    simkl = FakeSimkl()
    svc = ListStatusSync(q, simkl, FakeAniList())
    assert svc.set({'mal': 21}, 'dropped') is True
    assert simkl.calls == []
    item = next(iter(q.items().values()))
    assert item['kind'] == 'list' and item['status'] == 'dropped'


def test_anilist_gets_the_mapped_status(tmp_path):
    cfg = Cfg(tmp_path)
    q = SyncQueue(cfg.simkl_queue)
    anilist = FakeAniList()
    svc = ListStatusSync(q, FakeSimkl(), anilist)
    assert svc.set({'mal': 21, 'anilist': 5}, 'plantowatch') is True
    svcs = {i['svc']: i['status'] for i in q.items().values()}
    assert svcs == {'simkl': 'plantowatch', 'anilist': 'plantowatch'}
    assert ListStatusSync.mapping()['plantowatch'] == 'PLANNING'
    assert ListStatusSync.mapping()['hold'] == 'PAUSED'
    assert ListStatusSync.mapping()['dropped'] == 'DROPPED'


def test_unknown_status_and_empty_ids_are_refused(tmp_path):
    cfg = Cfg(tmp_path)
    q = SyncQueue(cfg.simkl_queue)
    svc = ListStatusSync(q, FakeSimkl(), FakeAniList())
    with pytest.raises(ValueError):
        svc.set({'mal': 1}, 'bingeing')
    assert svc.set({}, 'watching') is False
    assert len(q) == 0
