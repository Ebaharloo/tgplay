#!/usr/bin/env python3
"""test_player - mpv command builder + gpu-context pinning."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from tp.player import Player, gpu_context  # noqa: E402


def test_command():
    p = Player()
    cmd = p.command('http://x/f.mkv', title='T', extra=['--volume', '80'],
                    start=90, cut=30, ipc='/tmp/s.ipc')
    assert cmd[0] == 'mpv' and cmd[-1] == 'http://x/f.mkv'
    assert '--force-media-title=T' in cmd
    assert '--start=90' in cmd and '--end=-30' in cmd
    assert '--volume' in cmd and '80' in cmd
    assert '--input-ipc-server=/tmp/s.ipc' in cmd
    print('PASS player.command')


def test_gpu_context():
    assert gpu_context({'WAYLAND_DISPLAY': 'w'}) == 'wayland'
    assert gpu_context({'DISPLAY': ':0'}) == 'x11egl'
    assert gpu_context({}) is None
    # a user-supplied context is never overridden
    cmd = Player().command('u', extra=['--gpu-context=drm'])
    assert sum(f.startswith('--gpu-context') for f in cmd) == 1, cmd
    print('PASS gpu_context')


def main():
    test_command()
    test_gpu_context()
    print('PLAYER OK')


if __name__ == '__main__':
    main()
