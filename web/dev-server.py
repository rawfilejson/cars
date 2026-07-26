# Local static server with SPA fallback.
#
# Plain http.server answers 404 for an unknown path. This is the equivalent of
# Cloudflare Workers' not_found_handling = "single-page-application": an unknown
# path that isn't an asset falls back to index.html, so deep links like
# /car/myauto-121951594 work locally too.
#
# run: python web/dev-server.py [PORT]

from __future__ import annotations

import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


WEB_DIR = Path(__file__).resolve().parent


class SPAHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self):
        # dev only - never cache, so edits to config.js/i18n.js show on reload
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        rel = self.path.split("?", 1)[0].lstrip("/")
        target = WEB_DIR / rel
        if rel and (target.is_file() or target.is_dir()):
            return super().do_GET()
        if "." in os.path.basename(rel):
            return super().do_GET()
        self.path = "/"
        return super().do_GET()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5500
    server = ThreadingHTTPServer(("127.0.0.1", port), SPAHandler)
    print(f"SPA dev server on http://127.0.0.1:{port}/  (serving {WEB_DIR})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
