#!/usr/bin/env python3
"""test_translate - zh->en episode names, cached (MyMemory mocked)."""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.translate import Translator, has_cjk  # noqa: E402


class FakeHttp:
    def __init__(self, resp):
        self.resp = resp

    def request(self, *a, **k):
        return None

    def open(self, req):
        return io.BytesIO(json.dumps(self.resp).encode())


def test_translate():
    p = os.path.join(tempfile.mkdtemp(prefix='tgplay-tr-'), 'translations.json')
    tr = Translator(p, http=FakeHttp(
        {'responseData': {'translatedText': 'Darkness is coming'}}))
    assert has_cjk('天黑别出门')
    assert tr.translate('天黑别出门') == 'Darkness is coming'
    assert tr.get('天黑别出门') == 'Darkness is coming'
    assert tr.translate('Episode 1') == 'Episode 1'      # non-CJK passes through
    assert not has_cjk('Episode 1')
    # cached on disk -> a new instance needs no network
    tr2 = Translator(p, http=None)
    assert tr2.get('天黑别出门') == 'Darkness is coming'
    # a rate-limit message is rejected, not cached
    bad = Translator(os.path.join(tempfile.mkdtemp(), 'x.json'), http=FakeHttp(
        {'responseData': {'translatedText': 'MYMEMORY WARNING: LIMIT'}}))
    assert bad.translate('我是霸体') is None
    print('PASS translate (cache + filters)')


def test_batch():
    p = os.path.join(tempfile.mkdtemp(prefix='tgplay-trb-'), 'translations.json')
    tr = Translator(p, http=FakeHttp(
        {'responseData': {'translatedText': 'A\nB\nC'}}))
    tr.ensure(['天黑别出门', '我是霸体', '小魔崽子'])
    assert tr.get('天黑别出门') == 'A' and tr.get('我是霸体') == 'B' \
        and tr.get('小魔崽子') == 'C', tr._cache
    print('PASS translate batch (one request for many names)')


def main():
    test_translate()
    test_batch()
    print('TRANSLATE OK')


if __name__ == '__main__':
    main()
