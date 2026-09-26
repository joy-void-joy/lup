"""A command ``lup-launch run`` hands over, as a process of its own.

Run by ``test_trust_inbox``: given a port, it serves a page there and opens
it the one way a command opens a page, then keeps serving for a moment and
exits with a status of its own. Given no port, it opens nothing. A process
rather than a call in the test's own, because what is pinned is a launcher
following a child it handed its terminal to.
"""

import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from lup.trust.tab import shown_to_operator


def main(port: int, lasting: float, status: int) -> None:
    """Serve and open a page where a port is given, wait, and exit with ``status``."""
    if port:
        server = ThreadingHTTPServer(("127.0.0.1", port), SimpleHTTPRequestHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        shown_to_operator(f"http://127.0.0.1:{port}/")
    time.sleep(lasting)
    sys.exit(status)


if __name__ == "__main__":
    main(int(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3]))
