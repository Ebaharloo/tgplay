"""tp.proxy - one source-agnostic HTTP range proxy with RAM + disk caching.

`RangeProxy` serves `/f/<name>` for any registered `MediaSource`:

  * an 8MB RAM head (fast start) + 2MB RAM tail (mkv Cues) fetched by `prewarm`
  * an optional on-disk mirror window registered with `set_local`
  * live ranged reads from the source for the gaps

This is the single implementation that replaces `tg_server.py` and the two
inline handlers in `tg`/`tgp`.
"""
import os
import re
import threading
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional

from .sources import MediaSource

HEAD_B = 8 * 1024 * 1024
TAIL_B = 2 * 1024 * 1024
FILL = 8 * 1024 * 1024


@dataclass
class Stream:
    name: str
    source: MediaSource
    size: int = 0
    head: bytes = b''
    tail: bytes = b''
    local_path: Optional[str] = None
    local_lo: int = 0
    local_live: bool = False
    ready: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)


class RangeProxy:
    def __init__(self, port: int = 8898, host: str = '127.0.0.1',
                 head_b: int = HEAD_B, tail_b: int = TAIL_B, fill: int = FILL,
                 media_type: str = 'video/x-matroska'):
        self.host = host
        self.port = port
        self.head_b = head_b
        self.tail_b = tail_b
        self.fill = fill
        self.media_type = media_type
        self.streams: Dict[str, Stream] = {}
        self._srv = None
        self._started = False

    # --- registry ----------------------------------------------------------
    def register(self, name: str, source: MediaSource,
                 size: Optional[int] = None) -> Stream:
        st = self.streams.get(name)
        same_url = getattr(st.source, 'url', None) if st is not None else None
        if st is not None and (st.source is source or (
                same_url and same_url == getattr(source, 'url', None))):
            # same bytes under the same name (warm path, then the main loop):
            # keep the head/tail and any window publish() already attached
            st.source = source
            if size:
                st.size = size
            return st
        st = Stream(name=name, source=source, size=size or 0)
        self.streams[name] = st
        return st

    def get(self, name: str) -> Optional[Stream]:
        return self.streams.get(name)

    def url(self, name: str) -> str:
        return f'http://{self.host}:{self.port}/f/{urllib.parse.quote(name)}'

    def set_local(self, name: str, path: str, size: int, lo: int = 0,
                  live: bool = False):
        st = self.streams.get(name)
        if st is not None and os.path.exists(path):
            st.local_path = path
            st.size = size or st.size
            st.local_lo = lo
            st.local_live = live

    # --- prewarm -----------------------------------------------------------
    def prewarm(self, name: str, event: Optional[threading.Event] = None):
        """Fetch size + head (and tail) in the background; set `event` when the
        head is usable so the player can start."""
        st = self.streams.get(name)
        if st is None:
            if event:
                event.set()
            return
        if st.head:
            if event:
                event.set()
            return

        def run():
            try:
                if not st.size:
                    st.size = st.source.size
                if st.size:
                    st.head = st.source.read(0, min(self.head_b, st.size))
                    if event:
                        event.set()
                    if st.size > self.head_b:
                        st.tail = st.source.read(
                            max(self.head_b, st.size - self.tail_b), st.size)
            except Exception:
                pass
            finally:
                if event:
                    event.set()  # never wedge the waiter on a failed prewarm

        threading.Thread(target=run, daemon=True).start()

    # --- server ------------------------------------------------------------
    def start(self):
        if self._started:
            return self
        ThreadingHTTPServer.allow_reuse_address = True
        _Handler.proxy = self
        try:
            self._srv = ThreadingHTTPServer((self.host, self.port), _Handler)
        except OSError as ex:  # 98 EADDRINUSE / 48 on macOS
            if getattr(ex, 'errno', None) not in (48, 98):
                raise
            from . import log
            log.cprint(f'proxy: port {self.port} busy - using a free one')
            self._srv = ThreadingHTTPServer((self.host, 0), _Handler)
        self.port = self._srv.server_address[1]  # real port (also when 0)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        self._started = True
        return self

    def stop(self):
        if self._srv is not None:
            self._srv.shutdown()
            self._srv = None
            self._started = False

    # --- cache layers ------------------------------------------------------
    def serve_cached(self, st: Stream, s: int, length: int, wfile) -> int:
        """Write up to `length` bytes at `s` from RAM/mirror. 0 = miss."""
        head = st.head
        if s < len(head):
            take = min(length, len(head) - s)
            wfile.write(head[s:s + take])
            return take
        if st.tail and st.size and s >= st.size - len(st.tail):
            off = s - (st.size - len(st.tail))
            take = min(length, len(st.tail) - off)
            wfile.write(st.tail[off:off + take])
            return take
        if st.local_path and st.local_lo <= s:
            try:
                plen = os.path.getsize(st.local_path)
            except OSError:
                plen = 0
            if s < st.local_lo + plen:
                off = s - st.local_lo
                take = min(length, plen - off)
                with open(st.local_path, 'rb') as f:
                    f.seek(off)
                    wfile.write(f.read(take))
                return take
        return 0


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    proxy: Optional[RangeProxy] = None

    def log_message(self, *a):
        pass

    def _name(self) -> str:
        path = self.path.split('?', 1)[0]
        return (urllib.parse.unquote(path[len('/f/'):])
                if path.startswith('/f/') else urllib.parse.unquote(path.lstrip('/')))

    def _stream(self) -> Optional[Stream]:
        if self.proxy is None:
            return None
        return self.proxy.streams.get(self._name())

    def _size(self, st: Stream) -> int:
        return st.size or st.source.size

    def do_HEAD(self):
        try:
            self._do_head()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _do_head(self):
        st = self._stream()
        if st is None:
            return self.send_error(404)
        size = self._size(st)
        self.send_response(200)
        self.send_header('Content-Length', str(size))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Type', self.proxy.media_type)
        self.end_headers()

    def do_GET(self):
        try:
            self._do_get()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _do_get(self):
        st = self._stream()
        if st is None:
            return self.send_error(404)
        size = self._size(st)
        if not size:
            try:
                from . import log
                log.cprint(f'link: size unknown for "{self._name()}" — '
                           'CDN did not answer; retrying with a fresh link')
            except Exception:
                pass
            return self.send_error(503, 'size unknown')
        rng = self.headers.get('Range')
        s, fin = 0, size - 1
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)', rng)
            if m:
                s = int(m.group(1)) if m.group(1) else 0
                fin = int(m.group(2)) if m.group(2) else size - 1
        fin = min(fin, size - 1)
        if rng:
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {s}-{fin}/{size}')
        else:
            self.send_response(200)
        self.send_header('Content-Length', str(fin - s + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Type', self.proxy.media_type)
        self.end_headers()
        pos = s
        while pos <= fin:
            try:
                got = self.proxy.serve_cached(st, pos, fin - pos + 1, self.wfile)
            except Exception:
                return  # client closed (seek/quit) = normal
            if got:
                pos += got
                continue
            try:
                buf = st.source.read(pos, min(pos + self.proxy.fill, fin + 1))
            except Exception:
                return
            if not buf:
                return
            try:
                self.wfile.write(buf)
            except Exception:
                return
            pos += len(buf)
