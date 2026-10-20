"""tp.status - connection lights: is Simkl / AnimeGate / AniList connected?

`StatusProbe.check_all()` runs quick, bounded checks and returns one item
per service:

    {'key': 'simkl', 'name': 'Simkl', 'state': 'ok'|'warn'|'bad',
     'detail': 'connected as <user>' | 'not connected' | ...,
     'fix': 'simkl' | 'gate' | 'anilist'}   # what to do when not ok

The GUI shows these as coloured lights and offers the matching action
(Simkl PIN dialog, AnimeGate login page, AniList token note). Checks are
cheap: local token/cookie presence first, ONE short network call at most,
and the whole probe is meant to run on a worker thread.
"""
import os
from typing import List


class StatusProbe:
    def __init__(self, cfg, http=None, account=None, gate=None):
        self.cfg = cfg
        self.http = http
        self._account = account        # injectable for tests
        self._gate = gate

    # --- simkl ------------------------------------------------------------
    @property
    def account(self):
        if self._account is None:
            from .simkl_account import SimklAccount
            self._account = SimklAccount(self.cfg, self.http)
        return self._account

    def check_simkl(self) -> dict:
        acc = self.account
        if not acc.client_id:
            return _item('simkl', 'Simkl', 'bad', 'no client id configured',
                         'simkl')
        if not acc.logged_in():
            return _item('simkl', 'Simkl', 'bad',
                         'not connected - click to sign in (PIN)', 'simkl')
        who = acc.user()                    # one cheap authenticated call
        if who:
            return _item('simkl', 'Simkl', 'ok', f'connected as {who}',
                         'simkl')
        return _item('simkl', 'Simkl', 'warn',
                     'token rejected/expired - click to sign in again',
                     'simkl')

    # --- animegate cookie session --------------------------------------
    @property
    def gate(self):
        if self._gate is None:
            from .providers.animegate import GateAuth
            self._gate = GateAuth(self.http)
        return self._gate

    def check_gate(self) -> dict:
        try:
            ok, reason = self.gate.alive()
        except Exception as ex:
            return _item('gate', 'AnimeGate', 'warn', f'check failed ({ex})',
                         'gate')
        if ok:
            return _item('gate', 'AnimeGate', 'ok', reason or 'session ok',
                         'gate')
        return _item('gate', 'AnimeGate', 'bad',
                     f'{reason} - click to open the login page', 'gate')

    # --- anilist token (optional) --------------------------------------
    def check_anilist(self) -> dict:
        path = getattr(self.cfg, 'anilist_auth', None)
        tok = None
        if path:
            try:
                import json
                tok = json.load(open(path)).get('access_token')
            except Exception:
                tok = None
        if os.environ.get('AGP_ANILIST_TOKEN'):
            tok = os.environ['AGP_ANILIST_TOKEN']
        if tok:
            return _item('anilist', 'AniList', 'ok',
                         'token set (tracking enabled)', 'anilist')
        return _item('anilist', 'AniList', 'warn',
                     'tracking off (optional) - run: tgplay login', 'anilist')

    # --- all -------------------------------------------------------------
    def check_all(self) -> List[dict]:
        """All lights. Each check is independent: one failing service never
        hides the others."""
        out = []
        for fn in (self.check_simkl, self.check_gate, self.check_anilist):
            try:
                out.append(fn())
            except Exception as ex:
                out.append(_item(fn.__name__.replace('check_', ''),
                                 fn.__name__.replace('check_', '').title(),
                                 'warn', f'check failed ({ex})', ''))
        return out


def _item(key: str, name: str, state: str, detail: str, fix: str) -> dict:
    return {'key': key, 'name': name, 'state': state, 'detail': detail,
            'fix': fix}
