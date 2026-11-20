"""Calendar: ONE feed, today/upcoming, recently aired, future dates."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta                               # noqa: E402

from tp.tracking.calendar import CalendarSync, _FEED               # noqa: E402
from tracking_fakes import Cfg, FakeSimkl                          # noqa: E402


def rows():
    today = date.today()
    return [
        {'title': 'Today', 'simkl': 1, 'air_date': today.isoformat(),
         'next_ep': 5, 'kind': 'today'},
        {'title': 'Soon', 'simkl': 2,
         'air_date': (today + timedelta(days=3)).isoformat(),
         'next_ep': 1, 'kind': 'upcoming'},
        {'title': 'Later', 'simkl': 3,
         'air_date': (today + timedelta(days=30)).isoformat(),
         'next_ep': 1, 'kind': 'upcoming'},
    ]


def test_one_feed_serves_today_and_the_window():
    _FEED.clear()
    simkl = FakeSimkl()
    simkl.schedule_rows = rows()
    cal = CalendarSync(Cfg('/tmp'), client=simkl)
    assert [r['title'] for r in cal.calendar(0)] == ['Today']
    assert [r['title'] for r in cal.calendar(7)] == ['Today', 'Soon']
    assert simkl.calls == []                      # no per-row API call


def test_trending_uses_the_same_client_and_cache():
    _FEED.clear()
    simkl = FakeSimkl()
    cal = CalendarSync(Cfg('/tmp'), client=simkl)
    assert cal.trending() == [{'title': 'Trending', 'simkl': 1,
                               'kind': 'trending'}]


def test_recently_aired_and_future_derive_from_rows_once():
    today = date.today()
    lib = [{'title': 'A', 'air_date': (today - timedelta(days=2)).isoformat()},
           {'title': 'B', 'air_date': today.isoformat()},
           {'title': 'C', 'air_date': (today + timedelta(days=5)).isoformat()}]
    aired = CalendarSync.recently_aired(lib, days=7)
    assert [r['title'] for r in aired] == ['A']
    assert aired[0]['kind'] == 'aired'
    assert [r['title'] for r in CalendarSync.future(lib)] == ['B', 'C']
