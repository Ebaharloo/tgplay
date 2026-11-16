#!/usr/bin/env python3
"""test_chapters - own test model for the intro/outro skip feature (tp.chapters).

Named chapters win, the positional guess only fills a side the names missed,
and the mpv flags are the exact --script-opts string skip.lua reads.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.chapters import SkipResolver  # noqa: E402


def test_kind_reads_chapter_names():
    assert SkipResolver.kind('Intro') == 'op'
    assert SkipResolver.kind('Opening 2') == 'op'
    assert SkipResolver.kind('Ending') == 'ed'
    assert SkipResolver.kind('Creditless ED') == 'ed'
    assert SkipResolver.kind('Chapter 1') is None
    assert SkipResolver.kind(None) is None


def test_named_chapters_win():
    chs = [('Intro', 0.0, 90.0), ('Chapter 1', 90.0, 1300.0),
           ('Ending', 1300.0, 1420.0), ('Preview', 1420.0, 1440.0)]
    op, ed, osrc, esrc = SkipResolver._decide(chs)
    assert (op, ed) == ((0.0, 90.0), (1300.0, 1420.0))
    assert (osrc, esrc) == ('named', 'named')


def test_positional_fills_only_the_missing_side():
    # no named intro: the short leading chapter becomes 'op', the named 'ed' stays untouched
    chs = [('Part A', 0.0, 60.0), ('Part B', 60.0, 1400.0), ('Ending', 1400.0, 1440.0)]
    op, ed, osrc, esrc = SkipResolver._decide(chs)
    assert (op, osrc) == ((0.0, 60.0), 'positional')
    assert (ed, esrc) == ((1400.0, 1440.0), 'named')


def test_mode_names_disables_the_guess():
    chs = [('Part A', 0.0, 60.0), ('Part B', 60.0, 1400.0)]
    assert SkipResolver._decide(chs, 'names') == (None, None, None, None)


def test_mode_auto_ignores_titles():
    chs = [('Intro', 0.0, 90.0), ('Body', 90.0, 1400.0), ('Preview', 1400.0, 1440.0)]
    op, ed, osrc, esrc = SkipResolver._decide(chs, 'auto')
    assert (op, osrc) == ((0.0, 90.0), 'positional')
    assert (ed, esrc) == ((1400.0, 1440.0), 'positional')


def test_flags_are_the_script_opts_string():
    assert SkipResolver.opts_from((10, 90), (1300, 1400)) == [
        '--script-opts=skip-op_start=10,skip-op_end=90,skip-ed_start=1300,skip-ed_end=1400']
    assert SkipResolver.opts_from((10, 90), None, toggle=True) == [
        '--script-opts=skip-op_start=10,skip-op_end=90,skip-toggle=yes,skip-toggle_key=T']
    assert SkipResolver.opts_from(None, None) == []


def test_probe_parses_ffprobe_json(monkeypatch):
    payload = {'chapters': [
        {'start_time': '0.000000', 'end_time': '90.500000', 'tags': {'title': 'Intro'}},
        {'start_time': '90.5', 'end_time': '1400', 'tags': {'title': 'Main'}},
        {'start_time': 'oops'},                                  # skipped, not fatal
    ]}

    class R:
        stdout = json.dumps(payload)

    monkeypatch.setattr('subprocess.run', lambda *a, **k: R())
    got = SkipResolver().probe('http://x/file.mkv')
    assert [(c.title, c.start, c.end) for c in got] == [('Intro', 0.0, 90.5), ('Main', 90.5, 1400.0)]


if __name__ == '__main__':
    raise SystemExit(__import__('pytest').main([__file__, '-q']))
