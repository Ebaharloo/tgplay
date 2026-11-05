"""Loopback is never proxied, so the dead-proxy (offline) suite run is honest.

HTTP_PROXY=http://127.0.0.1:9 makes any real outbound request fail (that is
the point); without this, urllib would also send 127.0.0.1 test servers
through the dead proxy.
"""
import os

os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
