"""tp.features.warm - how a source prefetches the next episode's bytes.

tg/agp mirror bytes into the Prefetcher cache and hand them to the RangeProxy;
axp/zoro streams are HLS (no size to mirror), so ffmpeg pulls the whole thing
to disk and the next start opens a local file.
"""
import os
import re
import time
from abc import ABC
from typing import Optional

from ..prefetch import hls_to_file
from .. import log


class Warm(ABC):
    def run(self, ctx, st, name, ep) -> Optional[str]:
        """Warm the stream's bytes (ctx = the Playlist); return the local
        file path when the bytes ended up on disk, else None."""
        raise NotImplementedError


class MirrorWarm(Warm):
    """tg/agp: byte-mirror the remote file and register it with the proxy."""

    def run(self, ctx, st, name, ep):
        p = ctx.prefetcher.prefetch(name, st)
        if p and ctx.proxy is not None:
            lo = ctx.prefetcher.publish(ctx.proxy, name, p)
            log.cprint(f'next: ep{ep} prefetched from {lo} bytes - '
                       'proxy will serve it from disk')
        return None


class HlsWarm(Warm):
    """axp/zoro: ffmpeg pulls the HLS stream to a file in the cache dir.

    shortcut: a cache-less direct stream still mirrors (the pre-split path),
    only when no cache exists at all - axp/zoro sessions always have one."""

    def run(self, ctx, st, name, ep):
        if not getattr(st, 'direct', False):
            return MirrorWarm().run(ctx, st, name, ep)
        if ctx.cache is None:
            return None
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', name)
        ctx._sweep_hls()          # warmed files are one-shot: keep 2 days
        out = os.path.join(ctx.cache.path('hls'), safe)
        if not out.lower().endswith(('.mkv', '.mp4')):
            out = os.path.splitext(out)[0] + '.mkv'
        os.makedirs(os.path.dirname(out), exist_ok=True)
        t0 = time.monotonic()
        if hls_to_file(st.url, getattr(st, 'headers', None), out):
            log.cprint(f'next: on disk '
                       f'({os.path.getsize(out) // 1048576}MB in '
                       f'{time.monotonic() - t0:.0f}s)')
            return out
        log.cprint('next: stayed remote '
                   '(download did not finish in time)')
        return None
