"""WatchedSync: one class per service, the durable queue, tombstones on pull."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.simkl_sync import SEASON, SimklPusher, SyncQueue, Syncer   # noqa: E402
from tp.tracking.watched import (AniListWatched, LocalWatched,      # noqa: E402
                                 SimklWatched, WatchedSync)
from tracking_fakes import Cfg, FakeAniList, FakeSimkl              # noqa: E402


def rig(tmp, dead=False):
    cfg = Cfg(tmp)
    queue = SyncQueue(cfg.simkl_queue)
    simkl = FakeSimkl(dead=dead)
    anilist = FakeAniList()
    return cfg, queue, simkl, anilist, WatchedSync(cfg, queue, simkl,
                                                    anilist)


def test_each_service_reports_its_own_availability(tmp_path):
    cfg, _q, simkl, anilist, w = rig(tmp_path)
    names = {s.name for s in w.services}
    assert names == {'local', 'simkl', 'anilist'}          # all three here
    assert LocalWatched(cfg=cfg).enabled() is True
    assert SimklWatched(None).enabled() is False
    assert AniListWatched(None).enabled() is False


def test_episode_change_writes_locally_and_queues_once(tmp_path):
    _cfg, queue, _s, _a, w = rig(tmp_path)
    kind, on = w.change('mal:21', 'episode', 3, [1, 2, 3])
    assert (kind, on) == ('episode', True)
    assert w.state('mal:21')['eps'] == {3}
    w.queue_change(kind, on, {'num': 3, 'nums': [1, 2, 3]}, {'mal': 21})
    items = list(queue.items().values())
    assert len(items) == 1 and items[0]['kind'] == 'episode'


def test_season_mark_is_one_native_call_not_n_per_episode(tmp_path):
    _cfg, queue, _s, _a, w = rig(tmp_path)
    w.queue_change('season', True, {'num': 1, 'nums': [1, 2, 3]},
                   {'mal': 21})
    items = list(queue.items().values())
    assert len(items) == 1 and items[0]['kind'] == SEASON
    assert items[0]['ids'] == {'mal': 21}


def test_anilist_gets_its_own_queued_item(tmp_path):
    _cfg, queue, _s, a, w = rig(tmp_path)
    w.queue_change('episode', True, {'num': 2, 'nums': [1, 2]},
                   {'mal': 21, 'anilist': 5})
    svcs = {i['svc'] for i in queue.items().values()}
    assert svcs == {'simkl', 'anilist'}
    assert a.calls == []                      # queue first, never inline


def test_queue_durability_dead_network_then_exactly_one_call(tmp_path):
    _cfg, queue, simkl, _a, w = rig(tmp_path, dead=True)
    key = 'mal:21'
    w.change(key, 'episode', 3, [1, 2, 3])
    w.queue_change('episode', True, {'num': 3, 'nums': [1, 2, 3]},
                   {'mal': 21})
    syncer = Syncer(queue, pushers={'simkl': SimklPusher(simkl)})

    assert syncer.flush() == {'sent': 0, 'failed': 1, 'pending': 1}
    simkl.dead = False
    assert syncer.flush()['sent'] == 1
    assert simkl.calls == [('mark_episode_watched',
                            ({'mal': 21}, 1, 3))]
    syncer.flush()                            # already drained: no second call
    assert len(simkl.calls) == 1


def test_tombstone_pull_keeps_the_unmark_and_queues_the_remove(tmp_path):
    cfg, queue, simkl, _a, w = rig(tmp_path)
    key = 'mal:21'
    w.change(key, 'episode', 2, [1, 2], True)     # watched
    w.change(key, 'episode', 2, [1, 2], False)    # then unmarked here
    simkl.rows[21] = [{'seasons': [{'number': 1, 'episodes': [
        {'number': 1, 'watched': True,
         'last_watched_at': '2026-11-01T10:00:00Z'},
        {'number': 2, 'watched': True,
         'last_watched_at': '2026-11-02T10:00:00Z'}]}]}]

    assert w.pull(id_map=lambda k: {'mal': 21}) == 1   # ep1 added, ep2 not
    assert w.state(key)['eps'] == {1}
    items = list(queue.items().values())
    assert len(items) == 1
    assert items[0]['ep'] == 2 and items[0]['watched'] is False
    assert os.path.exists(cfg.simkl_activities)       # ONE stamp file


def test_pull_with_nothing_moved_costs_one_call(tmp_path):
    _cfg, _q, simkl, _a, w = rig(tmp_path)
    w.change('mal:21', 'episode', 1, [1], True)
    w.pull(id_map=lambda k: {'mal': 21})              # records the stamp
    simkl.calls.clear()
    assert w.pull(id_map=lambda k: {'mal': 21}) == 0
    assert all(name != 'watched' for name, _ in simkl.calls)
