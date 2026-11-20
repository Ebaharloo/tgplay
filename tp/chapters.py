"""tp.chapters - read a video's own chapters with ffprobe.

One job: URL + headers + timeout -> list[Chapter]. No skip decision here --
that is tp.skip.SkipDecider, which has no I/O.
"""
import json
import subprocess
from typing import List, NamedTuple, Optional

class Chapter(NamedTuple):
    title: str
    start: float
    end: float


class ChapterReader:
    def __init__(self, ffprobe: str = 'ffprobe', timeout: float = 30):
        self.ffprobe = ffprobe
        self.timeout = timeout

    def read(self, url: str, headers: Optional[dict] = None,
             timeout: Optional[float] = None) -> List[Chapter]:
        """The file's chapters; [] when it carries none or cannot be read."""
        cmd = [self.ffprobe, '-v', 'quiet', '-print_format', 'json',
               '-show_chapters']
        if headers:                     # some CDNs 403 without the Referer
            cmd += ['-headers', ''.join(f'{k}: {v}\r\n'
                                        for k, v in headers.items())]
        cmd.append(url)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout or self.timeout)
            raw = json.loads(r.stdout or '{}').get('chapters', [])
        except Exception:
            return []
        out = []
        for c in raw:
            try:
                out.append(Chapter((c.get('tags') or {}).get('title'),
                                   float(c['start_time']), float(c['end_time'])))
            except (KeyError, TypeError, ValueError):
                continue
        return out
