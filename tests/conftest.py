"""Loopback is never proxied, so the dead-proxy (offline) suite run is honest.

HTTP_PROXY=http://127.0.0.1:9 makes any real outbound request fail (that is
the point); without this, urllib would also send 127.0.0.1 test servers
through the dead proxy.
"""
import atexit
import os
import sys

os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'

# Qt widget tests leave a QApplication behind; PySide6 then segfaults inside the
# interpreter teardown *after* the pytest summary, which made `make finalize` exit 2
# on a fully green run. Registering the handler last (now, after Qt is loaded) makes
# it the first atexit hook, so the run exits with pytest's own status.
def pytest_sessionfinish(session, exitstatus):
    def _exit(status=int(exitstatus)):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)

    atexit.register(_exit)
