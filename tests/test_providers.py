#!/usr/bin/env python3
"""test_providers - animegate parsing + provider wiring + telegram byte source.

No network: the animegate module's site functions are monkeypatched and
Telegram uses a fake client. Run: python3 tests/test_providers.py
"""
import asyncio
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from tp.providers import animegate as ag  # noqa: E402
from tp.providers.telegram import (TelegramSource, fetch_exact, _retryable,  # noqa: E402
                                   logout)
from tp.sources import HttpSource  # noqa: E402

PAGE = ('<!DOCTYPE html><html><head>'
        '<meta name="csrf-token" content="CSRF123">'
        '</head><body>'
        '<div class="quality" data-id="0">720p</div>'
        ":links='[{\"id\":0,\"label\":\"720p\",\"data\":"
        "[{\"es\":1,\"link\":\"L1\"},{\"es\":2,\"link\":\"L2\"}]}]'"
        ':anime_id="14989"></body></html>')


def test_parse():
    groups, csrf, aid = ag.parse_page(PAGE)
    assert csrf == 'CSRF123' and aid == '14989', (csrf, aid)
    assert len(groups) == 1 and groups[0]['label'] == '720p'
    assert groups[0]['data'][0]['es'] == 1
    assert ag.slug_title('https://animegate.ir/anime/mushen-ji-20814#download') \
        == 'Mushen Ji'
    gs = [{'label': '480P'}, {'label': '720P'}, {'label': '1080P [x265]'}]
    assert ag.pick_group(gs, '720')['label'] == '720P'
    assert ag.pick_group(gs, 'x265')['label'] == '1080P [x265]'
    try:
        ag.pick_group(gs, '4k')
        raise AssertionError('expected no-match error')
    except ValueError:
        pass
    # empty groups: the page exists but has no servers — must be a CLEAN
    # user-readable error ('list index out of range' was the old bug)
    try:
        ag.pick_group([])
        raise AssertionError('expected no-servers error')
    except ValueError as ex:
        assert 'no quality servers' in str(ex), ex
    print('PASS animegate parsing')


def test_provider_no_servers():
    # a movie page with no release servers (Fanren Mulan movie case):
    # select() must raise the friendly NoServersYet, NOTHING like IndexError
    from tp.providers.base import NoServersYet
    ag.get_base = lambda url, cs, http: ([], 'CSRF', '14989')
    ag.all_eps = lambda aid, gid, group, csrf, cs, http: {}
    p = ag.AnimeGateProvider('https://animegate.ir/anime/fanren-xiu-xian-'
                             'zhuan-mulan-zhi-zhan-21616', cookies={})
    try:
        p.select(None)
        raise AssertionError('expected NoServersYet')
    except NoServersYet as ex:
        assert 'no release servers' in str(ex), ex
    except Exception as ex:                    # the old bug shape
        raise AssertionError(f'wrong error kind: {type(ex).__name__}: {ex}')
    # quality never crashes either: pick another site page with the data
    print('PASS animegate provider (no-servers page is a clean error)')


def test_provider():
    ag.get_base = lambda url, cs, http: (
        [{'id': 7, 'label': '720p', 'data': [
            {'es': 1, 'label': 'Ep 1', 'link': 'old1'},
            {'es': 2, 'label': 'Ep 2', 'link': 'old2'}]}], 'CSRF', '14989')
    ag.all_eps = lambda aid, gid, group, csrf, cs, http: {1: 'old1', 2: 'old2'}
    # per-episode refetch -> fresh signed link
    ag.fetch_eps_window = lambda aid, gid, s, e, csrf, cs, http: \
        [{'es': s, 'link': f'fresh{s}'}]

    p = ag.AnimeGateProvider('https://animegate.ir/anime/mushen-ji-20814',
                             quality='720', cookies={'XSRF-TOKEN': 'x'})
    assert p.episodes() == {1: 'Ep 1', 2: 'Ep 2'}, p.episodes()
    src = p.stream(2)
    assert isinstance(src, HttpSource) and src.url == 'fresh2', src
    print('PASS animegate provider')


# --- telegram ---------------------------------------------------------------
class FakeClient:
    async def iter_download(self, msg, offset=0, request_size=None,
                            chunk_size=None):
        end = min(offset + request_size, len(msg))
        for i in range(offset, end, 4096):
            yield msg[i:min(i + 4096, end)]


def test_telegram_source():
    data = bytes(range(256)) * 100  # 25600
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    try:
        src = TelegramSource(FakeClient(), loop, data, len(data))
        assert src.size == len(data)
        assert src.read(10, 20) == data[10:20]
        assert src.read(0, 4095) == data[:4095]
        assert src.read(len(data) - 5, len(data)) == data[-5:]
        assert src.read(5, 5) == b''

        # fetch_exact aligns to 4096 and returns exactly the requested slice
        got = asyncio.run_coroutine_threadsafe(
            fetch_exact(FakeClient(), data, 100, 50), loop).result()
        assert got == data[100:150], len(got)
    finally:
        loop.call_soon_threadsafe(loop.stop)
    print('PASS telegram source + fetch_exact')


def test_retry_and_logout():
    # only transient/flood errors are retried; auth errors are NOT (rate-limit)
    assert _retryable(OSError('reset')) and _retryable(TimeoutError())

    class Flood(Exception):
        seconds = 5
    assert _retryable(Flood())
    assert not _retryable(ValueError('auth')) and \
        not _retryable(RuntimeError('AuthKeyUnregistered'))

    # logout removes the session so a fresh login is possible
    import tempfile
    base = os.path.join(tempfile.mkdtemp(prefix='tgplay-sess-'), 'tg')
    open(base + '.session', 'wb').write(b'x')
    assert logout(base) is True and not os.path.exists(base + '.session')
    assert logout(base) is False
    print('PASS telegram retry rules + logout')


def test_two_line_titles():
    """Feed titles sometimes wrap on 2 lines; find_source must still match
    (the 'A Record of Mortal's Journey to Immortality' case: the AX result
    carries the English title, the AG results the romanized variants)."""
    from tp import library as lib

    def fake_search(q, http=None, sources=('agp', 'axp'), limit=12):
        return [
            {'title': 'Fanren Xiu Xian Zhuan: Mulan Zhi Zhan',
             'url': 'https://animegate.ir/anime/...-21616', 'source': 'agp'},
            {'title': "A Record Of Mortal's Journey To Immortality",
             'url': 'axp:a-record-of-mortals-journey-to-immortality-psj88',
             'source': 'axp'},
        ]

    got = lib.find_source("A Record of Mortal's\n"
                          "Journey to Immortality", http=None)
    assert got == ('axp', 'axp:a-record-of-mortals-journey-to-immortality-'
                           'psj88'), got
    print('PASS find_source matches a 2-line wrapped title')


def main():
    test_parse()
    test_two_line_titles()
    test_provider()
    test_telegram_source()
    test_retry_and_logout()
    print('PROVIDERS OK')


if __name__ == '__main__':
    main()
