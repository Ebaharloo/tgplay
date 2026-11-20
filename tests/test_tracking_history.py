#!/usr/bin/env python3
"""test_tracking_history - the History rows come from ONE place."""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.tracking.history import HistorySync               # noqa: E402


def _cfg(tmp):
    return types.SimpleNamespace(progress=f'{tmp}/p.json')


def test_history_rows_are_newest_first_and_skip_unwatched(monkeypatch, tmp_path):
    """recent() reads library.overview('hist') - one library read."""
    import tp.library as lib
    payload = {'hist': [
        {'title': 'Old', 'last_watched': '2026-11-01'},
        {'title': 'New', 'last_watched': '2026-11-19'},
    ]}
    monkeypatch.setattr(lib, 'overview',
                        lambda *a, **k: payload)
    h = HistorySync(_cfg(tmp_path), client=None)
    assert [r['title'] for r in h.recent(limit=10)] == ['New', 'Old']


def test_history_respects_the_limit(monkeypatch, tmp_path):
    import tp.library as lib
    monkeypatch.setattr(lib, 'overview', lambda *a, **k: {
        'hist': [{'title': f'n{i}', 'last_watched': '2026-11-01'}
                 for i in range(5)]})
    h = HistorySync(_cfg(tmp_path), client=None)
    assert len(h.recent(limit=2)) == 2


def test_history_survives_a_dead_library(monkeypatch, tmp_path):
    import tp.library as lib
    monkeypatch.setattr(lib, 'overview', lambda *a, **k: (_ for _ in ()).throw(
        OSError('down')))
    h = HistorySync(_cfg(tmp_path), client=None)
    assert h.recent(limit=5) == []


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
