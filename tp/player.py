"""tp.player - build/run the mpv command and watch its progress over IPC."""
import json
import os
import socket
import subprocess
import threading
import time
from typing import Callable, List, Optional

from .http import DEFAULT_UA


def gpu_context(env=None) -> Optional[str]:
    """Pin mpv to the session's real display so 'auto' can't fall through to
    DRM (which fails with 'Failed to acquire DRM master')."""
    env = env if env is not None else os.environ
    if env.get('WAYLAND_DISPLAY'):
        return 'wayland'
    if env.get('DISPLAY'):
        return 'x11egl'
    return None


class Player:
    def __init__(self, binary: str = 'mpv', user_agent: str = DEFAULT_UA,
                 referer: str = 'https://animegate.ir/'):
        self.binary = binary
        self.user_agent = user_agent
        self.referer = referer

    def command(self, url: str, *, title: Optional[str] = None,
                extra: Optional[List[str]] = None, start: Optional[int] = None,
                cut: Optional[int] = None, cache_bytes: str = '150MiB',
                readahead: int = 60, vo: str = 'gpu-next,gpu,dispmanx',
                pin_context: bool = True, ipc: Optional[str] = None) -> List[str]:
        cmd = [self.binary, '--ytdl=no',
               f'--user-agent={self.user_agent}',
               f'--referrer={self.referer}',
               f'--vo={vo}', '--cache=yes',
               f'--demuxer-max-bytes={cache_bytes}',
               f'--demuxer-readahead-secs={readahead}',
               '--demuxer-seekable-cache=yes']
        cmd += list(extra or [])
        if title:
            cmd.append('--force-media-title=' + title)
        if start is not None:
            cmd.append(f'--start={int(start)}')
        if cut:
            cmd.append(f'--end=-{int(cut)}')
        if pin_context and not any(f.startswith('--gpu-context') for f in cmd):
            gc = gpu_context()
            if gc:
                cmd.append('--gpu-context=' + gc)
        if ipc:
            cmd.insert(1, f'--input-ipc-server={ipc}')
        cmd.append(url)
        return cmd

    def play(self, cmd: List[str]) -> int:
        try:
            return subprocess.run(cmd).returncode
        except KeyboardInterrupt:
            return 4  # mpv got SIGINT too: treat as a user quit


class PosWatcher(threading.Thread):
    """Poll mpv's IPC time-pos. Reports each position and can fire a callback
    once when `fire_when(pos, duration)` first becomes true (the --next
    prefetch trigger), decoupled from the playlist."""

    def __init__(self, sock_path: str, interval: float = 10.0,
                 on_pos: Optional[Callable[[float], None]] = None,
                 fire_when: Optional[Callable[[float, float], bool]] = None,
                 on_fire: Optional[Callable[[], None]] = None,
                 wait: float = 60.0):
        super().__init__(daemon=True)
        self.sock = sock_path
        self.interval = interval
        self.on_pos = on_pos
        self.fire_when = fire_when
        self.on_fire = on_fire
        self.wait = wait
        self.last = 0.0

    def _query(self, prop: str) -> Optional[float]:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(3)
        try:
            c.connect(self.sock)
            c.send(json.dumps({'command': ['get_property', prop]}).encode()
                   + b'\n')
            data = c.recv(4096).decode()
        finally:
            c.close()
        for line in data.splitlines():
            if line.strip().endswith('}'):
                try:
                    v = json.loads(line).get('data')
                    if isinstance(v, (int, float)):
                        return v
                except Exception:
                    pass
        return None

    def run(self):
        for _ in range(int(self.wait)):
            if os.path.exists(self.sock):
                break
            time.sleep(1)
        else:
            return
        fired = False
        while os.path.exists(self.sock):
            time.sleep(self.interval)
            try:
                p = self._query('time-pos')
            except Exception:
                continue
            if p is None:
                continue
            self.last = p
            if self.on_pos:
                self.on_pos(p)
            if not fired and self.fire_when and self.on_fire and p > 0:
                try:
                    d = self._query('duration')
                    if d and self.fire_when(p, d):
                        self.on_fire()
                        fired = True
                except Exception:
                    pass
