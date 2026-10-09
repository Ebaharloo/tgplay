"""tp.icon - the app icon: asset paths + installing a desktop launcher.

Assets live in ``tp/assets`` (SVG + PNGs 16..512). ``install()`` drops them into
the user's hicolor theme and writes a ``tgplay.desktop`` entry, so the app shows
up in the KDE/GNOME launcher and taskbar with its icon.
"""
import os
import shutil
import subprocess
from typing import List, Optional

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
APP_ID = 'tgplay'
SIZES = [16, 24, 32, 48, 64, 128, 256, 512]


def svg() -> str:
    return os.path.join(ASSETS, f'{APP_ID}.svg')


def png(size: int = 256) -> Optional[str]:
    """Best available PNG at (or above, then below) the requested size."""
    order = [s for s in SIZES if s >= size] + [s for s in reversed(SIZES) if s < size]
    for s in order:
        p = os.path.join(ASSETS, f'{APP_ID}-{s}.png')
        if os.path.exists(p):
            return p
    p = os.path.join(ASSETS, f'{APP_ID}.png')
    return p if os.path.exists(p) else None


def _data_home() -> str:
    return os.environ.get('XDG_DATA_HOME') or os.path.join(
        os.path.expanduser('~'), '.local', 'share')


def desktop_text(exec_path: str) -> str:
    return (
        '[Desktop Entry]\n'
        'Type=Application\n'
        'Name=tgplay\n'
        'GenericName=Anime Streaming\n'
        'Comment=Search and stream AnimeGate, AnimeX and Telegram with mpv\n'
        f'Exec={exec_path}\n'
        f'Icon={APP_ID}\n'
        'Terminal=false\n'
        'Categories=AudioVideo;Player;\n'
        'Keywords=anime;stream;mpv;telegram;donghua;\n'
        f'StartupWMClass={APP_ID}\n'
        'StartupNotify=true\n'
    )


def _run(cmd: List[str]) -> None:
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=20)
    except Exception:
        pass


def install(exec_path: Optional[str] = None) -> List[str]:
    """Install icons + a desktop entry under the user's data dir. Returns the
    list of paths written."""
    data = _data_home()
    icons = os.path.join(data, 'icons', 'hicolor')
    written: List[str] = []

    for s in SIZES:
        src = os.path.join(ASSETS, f'{APP_ID}-{s}.png')
        if not os.path.exists(src):
            continue
        dst_dir = os.path.join(icons, f'{s}x{s}', 'apps')
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f'{APP_ID}.png')
        shutil.copyfile(src, dst)
        written.append(dst)

    if os.path.exists(svg()):
        dst_dir = os.path.join(icons, 'scalable', 'apps')
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f'{APP_ID}.svg')
        shutil.copyfile(svg(), dst)
        written.append(dst)

    apps = os.path.join(data, 'applications')
    os.makedirs(apps, exist_ok=True)
    exec_path = exec_path or shutil.which('tgplay') or shutil.which('agp') or os.path.join(
        os.path.expanduser('~'), '.local', 'bin', 'tgplay')
    desk = os.path.join(apps, f'{APP_ID}.desktop')
    with open(desk, 'w') as f:
        f.write(desktop_text(exec_path))
    written.append(desk)

    _run(['gtk-update-icon-cache', '-q', '-t', icons])
    _run(['update-desktop-database', apps])
    return written
