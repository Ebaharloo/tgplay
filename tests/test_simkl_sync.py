"""Offline queue, dedup and reconcile for Simkl push (tp/simkl_sync.py)."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.simkl_sync import (EP, SEASON, SHOW, SimklPusher, SyncQueue,  # noqa
                           Syncer, queue_key, reconcile)


def q(tmp_path, name='pending_sync.json'):
    return SyncQueue(str(tmp_path / name))


def test_queue_persists_across_restart(tmp_path):
    ids = {'mal': 21}
    q(tmp_path).put(ids, 1, 3, True)
    reopened = q(tmp_path)                 # new process, same file
    items = reopened.items()
    assert len(items) == 1
    item = next(iter(items.values()))
    assert item['ids'] == {'mal': 21} and item['ep'] == 3 and item['watched']


def test_mark_then_unmark_before_flush_sends_only_final_state(tmp_path):
    ids = {'mal': 21}
    queue = q(tmp_path)
    queue.put(ids, 1, 3, True)
    queue.put(ids, 1, 3, False)
    items = queue.items()
    assert len(items) == 1
    assert next(iter(items.values()))['watched'] is False


def test_season_and_show_do_not_collide_with_episodes(tmp_path):
    ids = {'simkl': 7}
    queue = q(tmp_path)
    queue.put(ids, 1, 3, True)
    queue.put(ids, 1, None, True, kind=SEASON)
    queue.put(ids, None, None, True, kind=SHOW)
    assert set(queue.items()) == {
        queue_key(ids, 1, 3, EP), queue_key(ids, 1, None, SEASON),
        queue_key(ids, None, None, SHOW)}
    assert len(queue) == 3


def test_one_item_failing_does_not_block_the_rest(tmp_path):
    queue = q(tmp_path)
    queue.put({'mal': 1}, 1, 1, True)
    queue.put({'mal': 2}, 1, 1, True)
    queue.put({'mal': 3}, 1, 1, True)
    sent = []

    def push(item):
        if item['ids']['mal'] == 2:
            raise RuntimeError('HTTP 500')
        sent.append(item['ids']['mal'])

    res = Syncer(queue, push=push).flush()
    assert res == {'sent': 2, 'failed': 1, 'pending': 1}
    assert sorted(sent) == [1, 3]
    left = next(iter(queue.items().values()))
    assert left['ids']['mal'] == 2 and left['tries'] == 1
    assert '500' in left['error']

    # network back: the retry empties the queue
    res = Syncer(queue, push=lambda it: sent.append(it['ids']['mal'])).flush()
    assert res['pending'] == 0 and sent == [1, 3, 2]


def test_new_state_queued_during_push_is_not_dropped(tmp_path):
    queue = q(tmp_path)
    ids = {'mal': 21}
    queue.put(ids, 1, 3, True)

    def push(item):
        queue.put(ids, 1, 3, False)        # user unmarks while it is in flight

    Syncer(queue, push=push).flush()
    items = queue.items()
    assert len(items) == 1 and next(iter(items.values()))['watched'] is False


def test_status_callback_and_stop(tmp_path):
    seen = []
    queue = q(tmp_path)
    queue.put({'mal': 1}, 1, 1, True)
    syncer = Syncer(queue, push=lambda it: None, interval=0.05,
                    on_status=seen.append)
    syncer.start()
    deadline = time.time() + 5
    while not seen and time.time() < deadline:
        time.sleep(0.02)
    syncer.stop()
    assert len(queue) == 0
    assert seen and seen[-1]['sent'] == 1


def test_no_account_keeps_items_queued(tmp_path):
    queue = q(tmp_path)
    queue.put({'mal': 1}, 1, 1, True)
    res = Syncer(queue).flush()            # not connected yet
    assert res['pending'] == 1 and len(queue) == 1


def test_pusher_calls_the_account_method_for_each_kind():
    class Acc:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            return lambda ids, *a: self.calls.append((name, ids) + a)

    acc = Acc()
    push = SimklPusher(acc)
    push({'ids': {'mal': 21}, 'kind': EP, 'season': 2, 'ep': 5,
          'watched': True})
    push({'ids': {'mal': 21}, 'kind': EP, 'season': 2, 'ep': 5,
          'watched': False})
    push({'ids': {'simkl': 9}, 'kind': SEASON, 'season': 1, 'watched': True})
    push({'ids': {'simkl': 9}, 'kind': SEASON, 'season': 1, 'watched': False})
    push({'ids': {'simkl': 9}, 'kind': SHOW, 'watched': True})
    push({'ids': {'simkl': 9}, 'kind': SHOW, 'watched': False})
    assert acc.calls == [
        ('mark_episode_watched', {'mal': 21}, 2, 5),
        ('unmark_episode_watched', {'mal': 21}, 2, 5),
        ('mark_season_watched', {'simkl': 9}, 1),
        ('unmark_season_watched', {'simkl': 9}, 1),
        ('mark_show_complete', {'simkl': 9}),
        ('unmark_show_complete', {'simkl': 9}),
    ]


def test_reconcile_newer_wins_and_conflict_logged():
    local = {(1, 1): 100.0, (1, 2): 300.0}
    remote = {(1, 1): 50.0, (1, 2): 400.0, (1, 3): 200.0}
    merged, conflicts = reconcile(local, remote)
    assert merged == {(1, 1): 100.0, (1, 2): 400.0, (1, 3): 200.0}
    assert [c['kept'] for c in conflicts] == ['local', 'remote']


def test_remote_watched_reads_seasons():
    class Acc:
        def watched(self, ids):
            assert ids == {'mal': 21}      # one show per pull, not the library
            return [{
                'show': {'ids': {'mal': 21, 'simkl': 4000}},
                'seasons': [{'number': 1, 'episodes': [
                    {'number': 1, 'watched': True,
                     'last_watched_at': '2026-11-01T10:00:00Z'},
                    {'number': 2, 'watched': True,
                     'last_watched_at': '2026-11-02T10:00:00Z'},
                    {'number': 3, 'watched': False}]}]}]

    from tp.simkl_sync import remote_watched
    got = remote_watched(Acc(), {'mal': 21})
    assert sorted(got) == [(1, 1), (1, 2)] and got[(1, 2)] > got[(1, 1)]
    assert remote_watched(Acc(), {}) == {}


def test_watched_batches_and_drops_unmatched():
    import tempfile
    from test_simkl_account import Cfg, FakeHttp
    from tp import simkl_account as sa

    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    row = {'result': 'found', 'seasons': [{'number': 1, 'episodes': [
        {'number': 4, 'watched': True, 'last_watched_at': '2026-11-01T10:00:00Z'}]}]}
    http = FakeHttp({'/sync/watched': [[{'result': 'not_found'}, row]]})
    acc = sa.SimklAccount(Cfg(tempfile.mkdtemp()), http)

    got = acc.watched([{'mal': i} for i in range(150)])
    assert len(got) == 2 and all(r['seasons'] for r in got)  # not_found dropped
    posts = [c for c in http.calls if c[0] == 'POST']
    assert len(posts) == 2                           # 100 + 50: under the cap
    assert 'extended=episodes' in posts[0][1]
    assert [len(json.loads(c[2])) for c in posts] == [100, 50]
    assert json.loads(posts[0][2])[0] == {'ids': {'mal': 0}}


def test_library_caches_and_fetches_only_the_delta(tmp_path):
    import tempfile
    from test_simkl_account import Cfg, FakeHttp
    from tp import simkl_account as sa

    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'

    class C(Cfg):
        @property
        def simkl_library(self):
            return str(tmp_path / 'simkl_activities.json')

        simkl_activities = simkl_library

    a = {'show': {'title': 'A', 'ids': {'simkl': 10}}, 'status': 'watching'}
    b = {'show': {'title': 'B', 'ids': {'simkl': 20}}, 'status': 'watching'}
    http = FakeHttp({'/sync/activities': {'all': 'A1'},
                     '/sync/all-items/anime': {'anime': [a, b]}})
    acc = sa.SimklAccount(C(str(tmp_path)), http)
    assert [r['title'] for r in acc.library()] == ['A', 'B']

    # same stamp: the cache answers, the library endpoint is not called
    http.calls.clear()
    assert [r['title'] for r in acc.library()] == ['A', 'B']
    assert not [c for c in http.calls if 'all-items' in c[1]]

    # stamp moved: one delta call carrying the saved stamp
    http.routes['/sync/activities'] = {'all': 'A2'}
    http.routes['/sync/all-items/anime'] = {'anime': [
        dict(b, watched_episodes_count=5)]}
    http.calls.clear()
    rows = acc.library()
    assert {r['title']: r['watched'] for r in rows} == {'A': 0, 'B': 5}
    assert 'date_from=A1' in http.calls[-1][1]

    # a failed delta keeps the rows AND the stamp, so the same window retries
    from test_simkl_account import Err
    http.routes['/sync/activities'] = {'all': 'A3'}
    http.routes['/sync/all-items/anime'] = Err(400, {'error': 'bad_request'})
    http.calls.clear()
    assert {r['title']: r['watched'] for r in acc.library()} == {'A': 0, 'B': 5}
    assert json.load(open(C(str(tmp_path)).simkl_library))['all'] == 'A2'
    http.routes['/sync/all-items/anime'] = {'anime': []}
    acc.library()
    assert 'date_from=A2' in http.calls[-1][1]


def test_ratings_list_and_remove():
    import tempfile
    from test_simkl_account import Cfg, FakeHttp
    from tp import simkl_account as sa

    os.environ['AGP_SIMKL_CLIENT_ID'] = 'cid'
    row = {'show': {'title': 'A', 'ids': {'simkl': 10}}, 'user_rating': 9}
    http = FakeHttp({'/sync/ratings/anime/9,10': {'anime': [row, 'junk']},
                     '/sync/ratings/anime': {'anime': [row]},
                     '/sync/ratings/remove': {}})
    acc = sa.SimklAccount(Cfg(tempfile.mkdtemp()), http)

    assert acc.ratings('9,10') == [row] and 'anime/9,10?' in http.calls[-1][1]
    assert acc.ratings() == [row] and http.calls[-1][1].count('/sync/ratings/anime?') == 1
    with open(acc.cfg.simkl_auth, 'w') as f:      # unrate needs a login
        json.dump({'access_token': 't', 'expires_at': time.time() + 999}, f)
    assert acc.unrate({'simkl': 10}) is True
    method, url, data, _ = http.calls[-1]
    assert method == 'POST' and '/sync/ratings/remove' in url
    assert json.loads(data) == {'anime': [{'ids': {'simkl': 10}}]}


def test_pull_gate_skips_an_unchanged_library(tmp_path):
    from tp.simkl_sync import pull_done, pull_gate

    class Acc:
        stamp = '2026-11-17T00:00:00Z'

        def activities(self):
            return {'all': self.stamp, 'anime': {'all': self.stamp}}

    path = str(tmp_path / 'simkl_activities.json')
    acc = Acc()
    moved, snap = pull_gate(acc, path)
    assert moved and snap == acc.stamp          # no snapshot yet: pull
    pull_done(path, snap)
    assert pull_gate(acc, path) == (False, snap)   # one call, nothing moved
    acc.stamp = '2026-11-17T01:00:00Z'
    assert pull_gate(acc, path) == (True, acc.stamp)

    # an account that reports no stamp must never block a pull
    blank = type('B', (), {'activities': lambda self: {}})()
    assert pull_gate(blank, path)[0] is True
    pull_done(path, '')                 # nothing to remember -> file untouched
    assert pull_gate(blank, path)[0] is True


def test_corrupt_queue_file_does_not_raise(tmp_path):
    p = tmp_path / 'pending_sync.json'
    p.write_text('not json')
    assert len(q(tmp_path)) == 0
    q(tmp_path).put({'mal': 1}, 1, 1, True)
    assert json.loads(p.read_text())['mal:1|s1|e1']['watched'] is True


def test_window_queues_a_watched_change_without_network(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from tp import gui_all
    from tp.config import Config
    from tp.gui_qt import _app

    _app()
    cfg = Config(home=str(tmp_path))
    win = gui_all.MainWindow(lambda *a, **k: None, cfg=cfg)
    win.state['session'] = type('S', (), {'title': 'X', 'mal_id': 21})()
    try:
        win.on_watched_changed('episode', True,
                               {'key': 'mal:21', 'num': 3, 'nums': [1, 2, 3]})
        win.on_watched_changed('episode', False,
                               {'key': 'mal:21', 'num': 3, 'nums': [1, 2, 3]})
        items = win._simkl_queue.items()
        assert len(items) == 1                 # mark + unmark = one final state
        item = next(iter(items.values()))
        assert item['ids'] == {'mal': 21} and item['watched'] is False

        win.state['session'] = type('S', (), {'title': 'X', 'mal_id': None})()
        win.on_watched_changed('season_unwatched', False,
                               {'key': 't:noname', 'num': 1, 'nums': [1, 2]})
        assert 'needs a Simkl/MAL id' in win.state['msg']

        win._libq.put(('simkl-sync', {'sent': 2, 'failed': 0, 'pending': 0}))
        win._drain_lib()
        assert 'synced' in win.state['msg']
    finally:
        win.deleteLater()
