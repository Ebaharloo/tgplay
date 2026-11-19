#!/usr/bin/env python3
"""test_telegram_creds - the api credentials come from outside the repo."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pytest  # noqa: E402

from tp.providers import telegram  # noqa: E402


def _home(tmp_path, monkeypatch, body=None):
    monkeypatch.setenv('HOME', str(tmp_path))
    for k in ('AGP_TG_API_ID', 'AGP_TG_API_HASH'):
        monkeypatch.delenv(k, raising=False)
    if body is not None:
        d = tmp_path / '.config' / 'tgp'
        d.mkdir(parents=True)
        (d / 'env').write_text(body)
    return tmp_path


def test_creds_read_from_the_env_file(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch,
          '# my app\nAGP_TG_API_ID=2040\nAGP_TG_API_HASH="abc123"\n')
    assert telegram.api_creds() == (2040, 'abc123')


def test_env_var_wins_over_the_file(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch, 'AGP_TG_API_ID=1\nAGP_TG_API_HASH=file\n')
    monkeypatch.setenv('AGP_TG_API_HASH', 'env')
    assert telegram.api_creds() == (1, 'env')


def test_missing_credential_names_the_fix(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match='AGP_TG_API_ID'):
        telegram.api_creds()
