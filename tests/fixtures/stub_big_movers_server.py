#!/usr/bin/env python3
"""Small controllable listener used by macOS lifecycle tests."""

import http.server
import os
import signal
import time


if os.environ.get("BIG_MOVERS_TEST_IGNORE_TERM") == "1":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

port = int(os.environ["PORTNUM"])

if os.environ.get("BIG_MOVERS_TEST_NO_LISTEN") == "1":
    while True:
        time.sleep(1)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", port), QuietHandler)
server.serve_forever()
