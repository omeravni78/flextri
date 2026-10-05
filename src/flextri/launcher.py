"""flexTri as a desktop app: start the web app, open it in the browser, live in the tray.

This is what the installed app (and ``flextri-app`` from a checkout) runs. It needs no terminal:

- picks port 8000, or any free port if 8000 is taken;
- a second launch only reopens the browser on the copy that is already running;
- a tray / menu bar icon has "Open flexTri" and "Quit"; without a tray, the "Quit" button in the
  app's header stops it;
- output goes to a log file in the data folder (``paths.log_dir()``) when there is no console.

``--self-test`` starts the app on a free port, loads the setup page and exits 0 if it works;
the release build runs it on every installer it makes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

from . import paths

PREFERRED_PORT = 8000
PING = "/app/ping"
log = logging.getLogger("flextri.launcher")


def _console_to_log() -> None:
    """A windowed app has no stdout/stderr; send them (and uvicorn's logging) to a file."""
    if sys.stdout is None or sys.stderr is None:
        f = open(paths.log_dir() / "flextri.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        if os.name != "nt":  # as uvicorn does; a port only lingering after a quick restart is free
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _any_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _running_file() -> Path:
    return paths.data_dir() / "running.json"


def _already_running() -> str | None:
    """The URL of a flexTri that is up already, if any."""
    try:
        port = json.loads(_running_file().read_text())["port"]
        url = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(url + PING, timeout=2) as r:
            return url if r.read() == b"flexTri" else None
    except (OSError, ValueError, KeyError):
        return None


def _desktop_app(stop):
    """The web app plus the two routes only the desktop launcher has."""
    from fastapi.responses import HTMLResponse, PlainTextResponse

    from .web.api import app

    app.state.stop = stop
    if getattr(app.state, "desktop", False):
        return app
    app.state.desktop = True

    @app.get(PING, include_in_schema=False)
    def ping():
        return PlainTextResponse("flexTri")

    @app.post("/app/quit", include_in_schema=False)
    def quit_app():
        threading.Timer(0.3, app.state.stop).start()  # let this page reach the browser first
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><title>flexTri</title>"
            "<body style='font:16px system-ui;margin:3em'><h1>flexTri has stopped.</h1>"
            "<p>You can close this tab. Open flexTri again from your apps when you want it back.</p>")

    return app


class Desktop:
    def __init__(self, port: int):
        import uvicorn

        self.icon = None
        self.server = uvicorn.Server(uvicorn.Config(_desktop_app(self.stop), host="127.0.0.1", port=port,
                                                    log_level="info"))
        self.url = f"http://127.0.0.1:{port}"
        self.thread = threading.Thread(target=self.server.run, name="flextri-server", daemon=True)

    def start(self, timeout: float = 30) -> None:
        self.thread.start()
        for _ in range(int(timeout / 0.05)):
            if self.server.started or not self.thread.is_alive():
                break
            threading.Event().wait(0.05)
        if not self.server.started:
            raise RuntimeError("flexTri's server did not start; see the log for why")

    def open(self) -> None:
        webbrowser.open(self.url)

    def stop(self) -> None:
        self.server.should_exit = True
        if self.icon is not None:
            self.icon.stop()

    def run_tray(self) -> bool:
        """Show the tray icon until Quit. False when this system has no tray to show it in."""
        try:
            import pystray  # on Linux this already fails when there is no display
            from PIL import Image
        except Exception:  # noqa: BLE001
            log.info("no tray icon: %s", sys.exc_info()[1])
            return False
        image = Image.open(paths.bundled("icon.png"))
        menu = pystray.Menu(pystray.MenuItem("Open flexTri", lambda: self.open(), default=True),
                            pystray.MenuItem("Quit", lambda: self.stop()))
        self.icon = pystray.Icon("flexTri", image, "flexTri", menu)
        try:
            self.icon.run()  # blocks; macOS needs it on the main thread
        except Exception:  # no tray (e.g. a Linux desktop without one): keep serving without it
            log.exception("no tray icon")
            self.icon = None
            return False
        return True

    def wait(self) -> None:
        self.thread.join()


def self_test() -> int:
    """Start on a free port, load the setup wizard and the static files, stop. 0 when all is well."""
    desk = Desktop(_any_free_port())
    try:
        desk.start()
        with urllib.request.urlopen(desk.url + "/", timeout=10) as r:
            page = r.read().decode()
        with urllib.request.urlopen(desk.url + "/static/htmx.min.js", timeout=10) as r:
            r.read()
        problems = [] if "olympic_8week_triathlete" in page else ["the Olympic plan is missing from the wizard"]
        try:
            import garminconnect  # noqa: F401
        except ImportError as e:
            problems.append(f"the Garmin client is missing ({e})")
    except Exception as e:  # noqa: BLE001  (any failure is a failed self-test)
        problems = [repr(e)]
    finally:
        desk.stop()
        desk.thread.join(10)
    print("flexTri self-test: " + ("OK" if not problems else "FAILED: " + "; ".join(problems)))
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="flextri-app", description="Run flexTri as a desktop app.")
    p.add_argument("--port", type=int, help=f"port to use (default {PREFERRED_PORT}, or any free one)")
    p.add_argument("--no-browser", action="store_true", help="don't open the browser")
    p.add_argument("--no-tray", action="store_true", help="no tray icon; stop with the Quit button or Ctrl+C")
    p.add_argument("--self-test", action="store_true", help="check this install works, then exit")
    args = p.parse_args(argv)
    _console_to_log()
    if args.self_test:
        return self_test()

    url = _already_running()
    if url:
        log.info("flexTri is already running at %s", url)
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    port = args.port or (PREFERRED_PORT if _port_free(PREFERRED_PORT) else _any_free_port())
    desk = Desktop(port)
    desk.start()
    _running_file().write_text(json.dumps({"port": port, "pid": os.getpid()}))
    log.info("flexTri is running at %s (data in %s)", desk.url, paths.data_dir())
    if not args.no_browser:
        desk.open()
    try:
        if args.no_tray or not desk.run_tray():
            desk.wait()
    except KeyboardInterrupt:
        desk.stop()
    desk.server.should_exit = True
    desk.thread.join(10)
    _running_file().unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
