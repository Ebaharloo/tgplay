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


def main():
    test_translate()
    print('TRANSLATE OK')


if __name__ == '__main__':
    main()
