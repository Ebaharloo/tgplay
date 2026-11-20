#!/usr/bin/env python3
"""test_simkl_auth_alert - a dead Simkl login must be impossible to miss.

User report 2026-11-20: the access token died and the app queued his marks
for hours with only a tiny 'Simkl warn' in the status line. Now: after an
auth failure the Syncer fires a critical desktop notification + an on_status
alert, throttled to one per ALERT_COOLDOWN.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tp.simkl_sync as sync_mod                            # noqa: E402
from tp.simkl_sync import Syncer, SyncQueue                 # noqa: E402


class DeadAuth:
    """A pusher that fails with the 401 the user saw."""
    def __call__(self, item):
        raise RuntimeError('simkl 401 /sync/history: Access token is invalid')


def _syncer(tmp_path, statuses, notifies):
    q = SyncQueue(str(tmp_path / 'pending.json'))
    s = Syncer(q, push=DeadAuth())
    s.on_status = statuses.append
    sync_mod.subprocess.run = lambda *a, **k: notifies.append(a)
    return s


def test_auth_failure_fires_a_loud_alert(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_mod, 'subprocess', types.SimpleNamespace(
        run=lambda *a, **k: None))
    statuses, _notifies = [], []
    monkeypatch.setattr(sync_mod.time, 'time',
                        lambda: 1_000_000.0)                    # fixed clock
    s = _syncer(tmp_path, statuses, _notifies)
    s.queue.put({'mal': 60568}, season=1, ep=1)
    s.flush()
    alerts = [x for x in statuses if x.get('alert') == 'simkl-auth']
    assert alerts, statuses
    assert 'log in' in alerts[0]['message'].lower(), alerts[0]
    assert alerts[0]['pending'] == 1, alerts[0]


def test_the_alert_is_throttled_not_per_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_mod, 'subprocess', types.SimpleNamespace(
        run=lambda *a, **k: None))
    statuses = []
    clock = {'t': 1_000_000.0}
    monkeypatch.setattr(sync_mod.time, 'time', lambda: clock['t'])
    s = _syncer(tmp_path, statuses, [])
    s.queue.put({'mal': 1}, season=1, ep=1)
    s.flush()
    s.queue.put({'mal': 2}, season=1, ep=2)
    clock['t'] += 60                                       # 1 min later: same item
    s.flush()
    assert len([x for x in statuses if x.get('alert') == 'simkl-auth']) == 1
    clock['t'] += sync_mod.ALERT_COOLDOWN + 1              # after the cooldown
    s.queue.put({'mal': 3}, season=1, ep=3)
    s.flush()
    assert len([x for x in statuses if x.get('alert') == 'simkl-auth']) == 2


def test_a_working_sync_never_alerts(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_mod, 'subprocess', types.SimpleNamespace(
        run=lambda *a, **k: None))
    statuses = []
    q = SyncQueue(str(tmp_path / 'p.json'))
    s = Syncer(q, push=lambda item: None)                  # push succeeds
    s.on_status = statuses.append
    s.queue.put({'mal': 5}, season=1, ep=1)
    s.flush()
    assert not [x for x in statuses if x.get('alert')], statuses


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
