"""The schedule/discover feeds: CDN JSON, no auth, one fetch per hour.

The panels only ever see plain library-shaped rows, so these tests pin the
row shape, the today/window filtering and the "a dead CDN must not raise".
"""
import io
import json
from datetime import date, timedelta

import pytest

from tp.config import Config
from tp.simkl_extra import SimklExtra, _FEEDS


class FakeHttp:
    """Answers every GET with one canned body and counts the calls."""
    def __init__(self, body):
        self.body = body if isinstance(body, (bytes, bytearray)) \
            else json.dumps(body).encode()
        self.calls = []

    def request(self, url, headers=None, method='GET', data=None):
        self.calls.append(url)
        return url

    def open(self, req, timeout=None, tries=None):
        return io.BytesIO(self.body)


class FakeAcc:
    """The bits of SimklAccount the random pick touches."""
    client_id = 'cid'
    http = None

    def __init__(self, answer):
        self.answer = answer

    def _api(self, path, *a, **kw):
        assert path == '/search/random'
        return self.answer


def _row(title, day, ep=1, simkl=1):
    return {'title': title, 'date': f'{day.isoformat()}T12:00:00+00:00',
            'episode': {'episode': ep}, 'ids': {'simkl_id': simkl}}


@pytest.fixture(autouse=True)
def _fresh():
    _FEEDS.clear()
    yield
    _FEEDS.clear()


def test_calendar_keeps_the_window_and_sorts(tmp_path):
    today = date.today()
    body = [_row('Later', today + timedelta(days=3), simkl=3),
            _row('Now', today, ep=7),
            _row('Old', today - timedelta(days=2), simkl=2)]
    ex = SimklExtra(Config(home=str(tmp_path)), FakeHttp(body))

    rows = ex.calendar()                       # days=0 is today's slice
    assert [r['title'] for r in rows] == ['Now']
    assert rows[0]['kind'] == 'today' and rows[0]['next_ep'] == 7
    assert rows[0]['simkl'] == 1

    rows = ex.calendar(days=3)
    assert [r['title'] for r in rows] == ['Now', 'Later']
    assert rows[1]['kind'] == 'upcoming'


def test_calendar_is_cached_for_an_hour(tmp_path):
    http = FakeHttp([_row('Now', date.today())])
    ex = SimklExtra(Config(home=str(tmp_path)), http)
    ex.calendar()
    ex.calendar()
    assert len(http.calls) == 1
    assert 'data.simkl.in/calendar/anime.json' in http.calls[0]


def test_trending_rows_carry_the_trending_kind(tmp_path):
    http = FakeHttp([_row('Hot', date.today(), simkl=9)])
    ex = SimklExtra(Config(home=str(tmp_path)), http)
    rows = ex.trending()
    assert [(r['title'], r['kind'], r['simkl']) for r in rows] == \
        [('Hot', 'trending', 9)]
    assert 'today_100.json' in http.calls[0]


def test_a_dead_cdn_returns_rows_not_an_exception(tmp_path):
    ex = SimklExtra(Config(home=str(tmp_path)), FakeHttp(b'<html>502</html>'))
    assert ex.calendar() == []
    assert ex.trending() == []
    assert _FEEDS == {}                        # nothing cached, next call retries


def test_random_becomes_a_searchable_title(tmp_path):
    ex = SimklExtra(Config(home=str(tmp_path)), acc=FakeAcc(
        {'simkl_id': 7,
         'simkl_url': 'https://simkl.com/anime/12345/frieren-beyond/'}))
    assert ex.random() == {'simkl': 7, 'title': 'frieren beyond'}

    ex = SimklExtra(Config(home=str(tmp_path)), acc=FakeAcc({}))
    assert ex.random() == {}
