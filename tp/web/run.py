"""tp.web.run - start the server, open a chromeless window, stop on exit.

The window is the browser's app mode (no tabs, no URL bar); closing it ends
the server. Falls back to a normal browser window when no Chromium is found.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from .. import log
from .server import HOST, PORT, serve


def window_cmd(url: str):
    """The chromeless-window command for `url`, or None when there is none."""
    for name in ('chromium', 'chromium-browser', 'google-chrome',
                 'google-chrome-stable', 'microsoft-edge'):
        exe = shutil.which(name)
        if exe:
            return [exe, f'--app={url}']
    exe = shutil.which('firefox')
    return [exe, '--new-window', url] if exe else None


def main(argv=None) -> int:
    port = int(os.environ.get('TPLAY_WEB_PORT') or PORT)
    server = serve(port)
    url = f'http://{HOST}:{server.server_address[1]}/'
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.cprint(f'web: {url}')
    cmd = window_cmd(url)
    try:
        if cmd:
            proc = subprocess.Popen(cmd)
            while proc.poll() is None:
                time.sleep(0.4)
        else:
            log.cprint('web: no chromium/firefox found - open the URL above')
            webbrowser.open(url)
            while True:
                time.sleep(0.4)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
