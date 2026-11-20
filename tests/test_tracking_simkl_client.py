#!/usr/bin/env python3
"""test_tracking_simkl_client - the ONE Simkl REST client + CDN feeds."""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone                      # noqa: E402
from tp.tracking.simkl_client import SimklClient            # noqa: E402

# LOCAL today as a bare date - the calendar filter converts each row to the
# local timezone and compares against date.today(); hardcoded dates go stale
TODAY = datetime.now().astimezone().strftime('%Y-%m-%d')


def _cfg(tmp):
    cfg = types.SimpleNamespace(progress=f'{tmp}/p.json', conf=tmp,
                                simkl_activities=f'{tmp}/st.json',
                                simkl_library=f'{tmp}/lib.json',
                                simkl_auth=f'{tmp}/auth.json',
                                mal_ids=f'{tmp}/mal.json',
                                ep_titles=f'{tmp}/t.json',
                                translations=f'{tmp}/tr.json',
                                watched=f'{tmp}/w.json',
                                tg_session=f'{tmp}/tg')
    os.makedirs(tmp, exist_ok=True)
    json.dump({'client_id': 'cid'}, open(f'{tmp}/simkl.json', 'w'))
    return cfg


FEED = {
    'metadata': {'1': {'title': 'Mine', 'ids': {'mal': 11}},
                 '9': {'title': 'Other', 'ids': {'mal': 99}}},
    # dates are relative to today - hardcoded dates go stale at midnight
    'calendar': [
        {'simkl_id': 9, 'date': TODAY + 'T11:00:00Z',
         'episode': {'episode': 568, 'title': 'ep568'}},
        {'simkl_id': 1, 'date': TODAY + 'T10:00:00Z',
         'episode': {'episode': 25, 'title': 'ep25'}},
    ],
}


def _patch(monkeypatch, payload):
    import tp.tracking.simkl_client as sc
    monkeypatch.setattr(sc, 'feed',
                        lambda http, url, client_id=None: payload)


def test_client_id_comes_from_cfg(tmp_path):
    assert (SimklClient(_cfg(tmp_path)).client_id or '').startswith('cid')


def test_calendar_filters_to_the_given_ids(tmp_path, monkeypatch):
    _patch(monkeypatch, FEED)
    rows = SimklClient(_cfg(tmp_path)).calendar(14, {1})
    assert [r['title'] for r in rows] == ['Mine'], rows
    assert rows[0]['mal'] == 11 and rows[0]['next_ep'] == 25


def test_calendar_without_ids_returns_the_whole_feed_sorted(tmp_path, monkeypatch):
    _patch(monkeypatch, FEED)
    rows = SimklClient(_cfg(tmp_path)).calendar(14, None)
    assert [r['title'] for r in rows] == ['Mine', 'Other']   # soonest first


def test_trending_reads_the_feed(tmp_path, monkeypatch):
    _patch(monkeypatch, [{'title': 'T', 'simkl': 1, 'kind': 'trending'}])
    assert SimklClient(_cfg(tmp_path)).trending()[0]['title'] == 'T'


def test_a_dead_feed_raises_the_wrapper_degrades(tmp_path, monkeypatch):
    import pytest
    import tp.tracking.simkl_client as sc
    monkeypatch.setattr(sc, 'feed', lambda *a, **k: (_ for _ in ()).throw(
        OSError('cdn down')))
    c = SimklClient(_cfg(tmp_path))
    with pytest.raises(OSError):
        c.calendar(14, set())

if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
