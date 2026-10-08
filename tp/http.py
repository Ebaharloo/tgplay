"""tp.http - HTTP with retries and exact byte-range fetches.

Central home for the retry rules (transient CDN blips such as SSL handshake
timeouts must not become hard 502s) that used to be duplicated between
tg_server.py and agp. Real HTTP status errors (expired link 403/404) are NOT
retried - the caller decides.
"""
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_UA = 'Mozilla/5.0 Gecko/20100101 Firefox/130.0'


def _quiet_close(r):
    """py3.14: a dead socket makes close() raise before the closed flag is set,
    so the GC finalizer re-raises at exit. Shadow it on failure."""
    try:
        r.close()
    except Exception:
        try:
            r.close = lambda: None
        except Exception:
            pass


class HttpClient:
    def __init__(self, user_agent=DEFAULT_UA, retries=3, backoff=0.5,
                 timeout=60, nconn=10):
        self.user_agent = user_agent
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self.nconn = nconn

    # --- open (retrying) ---------------------------------------------------
    def request(self, url, headers=None, method='GET', data=None):
        h = {'User-Agent': self.user_agent, 'Accept': '*/*'}
        if headers:
            h.update(headers)
        return urllib.request.Request(url, headers=h, data=data, method=method)

    def open(self, req, timeout=None, tries=None):
        """urlopen with a few retries for transient network blips."""
        n = tries or self.retries
        last = None
        for i in range(n):
            try:
                return urllib.request.urlopen(req, timeout=timeout or self.timeout)
            except urllib.error.HTTPError:
                raise  # real CDN answer (expired link etc): caller decides
            except Exception as ex:
                last = ex
                if i + 1 < n:
                    time.sleep(self.backoff * (i + 1))
        raise last

    # --- exact bytes -------------------------------------------------------
    def range_bytes(self, url, headers, lo, hi, timeout=None, tries=None):
        """Exact bytes [lo, hi); a short buffer on EOF is returned as-is."""
        if hi <= lo:
            return b''
        h = dict(headers or {})
        h.setdefault('User-Agent', self.user_agent)
        h['Range'] = f'bytes={lo}-{hi - 1}'
        r = self.open(self.request(url, headers=h), timeout, tries)
        buf = bytearray()
        need = hi - lo
        try:
            while len(buf) < need:
                chunk = r.read(min(1024 * 1024, need - len(buf)))
                if not chunk:
                    break
                buf += chunk
        finally:
            _quiet_close(r)
        return bytes(buf)

    def chunk(self, url, headers, lo, hi, timeout=None, nconn=None):
        """Bytes [lo, hi) fetched over nconn parallel connections, in order.

        The CDN throttles each connection, so a big span is split into ~1MB
        pieces fetched concurrently. Raises on a short read so the caller keeps
        whatever it already wrote.
        """
        span = hi - lo
        if span <= 0:
            return b''
        if span <= 1024 * 1024:
            return self.range_bytes(url, headers, lo, hi, timeout)
        piece = 1024 * 1024
        bounds = [(x, min(x + piece, hi)) for x in range(lo, hi, piece)]
        workers = min(nconn or self.nconn, len(bounds))
        out = [None] * len(bounds)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(self.range_bytes, url, headers, s, e, timeout): i
                    for i, (s, e) in enumerate(bounds)}
            for f in as_completed(futs):
                i = futs[f]
                b = f.result()
                s, e = bounds[i]
                if len(b) != e - s:
                    raise OSError('short read from CDN')
                out[i] = b
        return b''.join(out)
