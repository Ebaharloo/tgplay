#!/usr/bin/env python3
"""test_tracking_anilist_client - the one AniList GraphQL surface."""
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tp.tracking.anilist_client import Tracker             # noqa: E402


def _cfg(tmp):
    """The auth file the Tracker reads (cfg.anilist_auth)."""
    cfg = types.SimpleNamespace(progress=f'{tmp}/p.json', conf=tmp,
                                anilist_auth=f'{tmp}/anilist_auth.json')
    os.makedirs(tmp, exist_ok=True)
    return cfg


def _tracker(tmp, token='tok'):
    cfg = _cfg(tmp)
    json.dump({'token': token}, open(cfg.anilist_auth, 'w'))
    return Tracker(cfg)


def _patch_gql(monkeypatch, calls, reply):
    def fake(self, query, variables=None, token=None):
        calls.append((query, variables, token))
        return reply
    monkeypatch.setattr(Tracker, '_gql', fake)


def test_enabled_requires_a_token(tmp_path, monkeypatch):
    monkeypatch.delenv('AGP_ANILIST_TOKEN', raising=False)
    monkeypatch.delenv('AGP_NO_TRACK', raising=False)
    cfg = _cfg(tmp_path)
    json.dump({}, open(cfg.anilist_auth, 'w'))
    assert Tracker(cfg).enabled() is False


def test_save_progress_sends_the_mutation(tmp_path, monkeypatch):
    t = _tracker(tmp_path)
    calls = []
    _patch_gql(monkeypatch, calls, {'data': {'SaveMediaListEntry': {'id': 1}}})
    result = t.save_progress(4242, 7, total=12)
    assert result == {'id': 1}, result
    q, vars_, tok = calls[0]
    assert 'SaveMediaListEntry' in q, q
    assert vars_ == {'id': 4242, 'p': 7, 's': 'CURRENT'}, vars_
    assert 'status' in q, q                     # the status field is in the query
    assert tok is None   # the caller passes no token; _gql resolves the stored one


def test_media_goes_through_the_single_runner(tmp_path, monkeypatch):
    t = _tracker(tmp_path)
    calls = []
    _patch_gql(monkeypatch, calls,
               {'data': {'Media': {'id': 4242, 'title': {'romaji': 'X'}}}})
    media = t.media(4242)
    assert media['id'] == 4242
    assert calls[0][2] is None                 # read query: no token needed


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
