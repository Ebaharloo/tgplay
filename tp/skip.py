"""tp.skip - intro/outro skip flags.

Order: the mkv's OWN chapters first (see tp.chapters), then ani-skip
(aniskip.com) when the file carries nothing. Produces the `--script-opts` that
skip.lua consumes, so the player just gets a list of mpv args.
"""
import shutil
import subprocess
from typing import List, Optional

from .chapters import SkipResolver


class AniSkip:
    def __init__(self, binary: str = 'ani-skip'):
        self.binary = binary

    def available(self) -> bool:
        return bool(shutil.which(self.binary))

    def flags(self, mal_id: int, ep: int, toggle: bool = False
              ) -> Optional[List[str]]:
        """[] when ani-skip has no data, None when it is unavailable."""
        if not self.available():
            return None
        args = [self.binary, '-i', str(mal_id), '-e', str(ep)]
        if toggle:
            args.append('--toggle')
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=60)
        except Exception:
            return None
        out = (r.stdout or '').strip()
        if not out:
            return []
        return [t for t in out.split() if t.startswith('--')]


class SkipService:
    def __init__(self, resolver: Optional[SkipResolver] = None,
                 ani_skip: Optional[AniSkip] = None, metadata=None):
        self.chapters = resolver or SkipResolver()
        self.ani = ani_skip or AniSkip()
        self.meta = metadata

    def flags(self, *, title: str, ep: int, url: Optional[str] = None,
              mode: str = 'all', toggle: bool = False,
              timeout: float = 30) -> List[str]:
        if url:
            f = self.chapters.flags(url, mode, toggle, timeout)
            if f:
                return f
        mal = None
        if self.meta is not None:
            mal = self.meta.resolve_mal(title, ask=False)
        if mal is None or not self.ani.available():
            return []
        return self.ani.flags(mal, ep, toggle) or []
