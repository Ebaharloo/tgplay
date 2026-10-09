#!/usr/bin/env python3
"""test_app - the shared launcher wrapper: logfile + crash handling."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tp import app, log  # noqa: E402


def _env(d):
    os.environ['AGP_LOG_DIR'] = d
    os.environ['AGP_NO_DIALOG'] = '1'   # never pop a dialog in tests


def test_run_ok_writes_log():
    d = tempfile.mkdtemp()
    _env(d)
    try:
        def ok():
            log.cprint('hello from the app')
            return 0
        rc = app.run(ok, 'unittest')
        assert rc == 0, rc
        p = os.path.join(d, 'unittest.log')
        assert os.path.exists(p)
        assert 'hello from the app' in open(p).read()
    finally:
        os.environ.pop('AGP_LOG_DIR', None)
        os.environ.pop('AGP_NO_DIALOG', None)
    print('PASS app run + logfile')


def test_run_crash_logged():
    d = tempfile.mkdtemp()
    _env(d)
    try:
        def boom():
            raise RuntimeError('kaboom')
        rc = app.run(boom, 'unittest2')
        assert rc == 1, rc
        txt = open(os.path.join(d, 'unittest2.log')).read()
        assert 'kaboom' in txt, txt
        assert log.LOGFILE is None          # closed + reset after a run
    finally:
        os.environ.pop('AGP_LOG_DIR', None)
        os.environ.pop('AGP_NO_DIALOG', None)
    print('PASS app crash -> logged, rc=1')


def test_open_logfile_records_history():
    d = tempfile.mkdtemp()
    try:
        log.open_logfile(os.path.join(d, 'h.log'))
        log.cprint('shown: a line')
        log.LOGFILE.close()
        log.LOGFILE = None
        assert 'shown: a line' in open(os.path.join(d, 'h.log')).read()
        assert any('shown: a line' in x for x in log.HISTORY)
    finally:
        log.LOGFILE = None
    print('PASS open_logfile records to file + history')


def main():
    test_run_ok_writes_log()
    test_run_crash_logged()
    test_open_logfile_records_history()
    print('APP OK')


if __name__ == '__main__':
    main()
