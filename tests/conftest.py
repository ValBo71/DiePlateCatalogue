"""Test infrastructure: runs a real instance of the app against a throwaway copy of the demo
database, on its own port, for the duration of the test session.

Nothing here ever touches the repo's own database/catalog.db or uploads/ - each session gets a
fresh temp directory (see live_app), so tests can freely create, edit and delete tools without
disturbing the demo data or interfering with a developer's own running instance.
"""
from __future__ import annotations

import collections
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class LiveApp:
    base_url: str
    db_dir: Path


def _drain_into(pipe, buffer: collections.deque) -> None:
    """Continuously reads a subprocess pipe into a bounded ring buffer, in a daemon thread.

    Necessary, not just tidy: Werkzeug logs every request, and nothing was reading app.py's
    stdout while tests ran (only the fixture's teardown ever called .read()). Once the OS pipe
    buffer filled - which happened reliably partway through this suite - the next write from the
    app's own logging call blocked, and with it the request thread that triggered the log line,
    which surfaced as an unrelated-looking client-side read timeout on the *next* request.
    """
    for line in iter(pipe.readline, ""):
        buffer.append(line)


@pytest.fixture(scope="session")
def live_app(tmp_path_factory) -> LiveApp:
    """Starts the Flask app once for the whole test session, on a copy of the demo database."""
    work_dir = tmp_path_factory.mktemp("catalog-app")
    db_dir = work_dir / "database"
    upload_dir = work_dir / "uploads"
    db_dir.mkdir()
    upload_dir.mkdir()

    shutil.copy(REPO_ROOT / "database" / "catalog.db", db_dir / "catalog.db")
    for item in (REPO_ROOT / "uploads").iterdir():
        if item.is_file():
            shutil.copy(item, upload_dir / item.name)

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = {
        "CATALOG_DB_FOLDER": str(db_dir),
        "CATALOG_UPLOAD_FOLDER": str(upload_dir),
        "CATALOG_PORT": str(port),
    }
    process = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "app.py")],
        cwd=REPO_ROOT,
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log_tail: collections.deque = collections.deque(maxlen=500)
    threading.Thread(target=_drain_into, args=(process.stdout, log_tail), daemon=True).start()

    try:
        _wait_for_server(base_url, process, log_tail)
        yield LiveApp(base_url=base_url, db_dir=db_dir)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if os.environ.get("CATALOG_TEST_DEBUG_LOG"):
            print("\n----- app.py stdout/stderr (tail) -----\n" + "".join(log_tail) + "\n----- end -----\n")


def _wait_for_server(base_url: str, process: subprocess.Popen, log_tail: collections.deque, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"App process exited early (code {process.returncode}):\n{''.join(log_tail)}")
        try:
            requests.get(f"{base_url}/login", timeout=1)
            return
        except requests.RequestException:
            time.sleep(0.3)
    raise TimeoutError(f"App did not start listening on {base_url} within {timeout}s")


def _login(base_url: str, username: str, password: str) -> requests.Session:
    session = requests.Session()
    # The app's dev server (Werkzeug, threaded=True) can wedge a request on a reused keep-alive
    # connection under this suite's rapid sequential requests - a connection accepted at the TCP
    # level but never reaching the WSGI app, seen as a client-side read timeout. Nothing here needs
    # keep-alive, so closing every connection sidesteps it.
    session.headers["Connection"] = "close"
    response = session.post(
        f"{base_url}/login",
        data={"username": username, "password": password},
        headers={"Origin": base_url},
        allow_redirects=False,
        timeout=10,
    )
    if response.status_code != 302:
        raise AssertionError(f"login as {username!r} failed: HTTP {response.status_code}")
    return session


@pytest.fixture()
def admin_session(live_app: LiveApp):
    with _login(live_app.base_url, "admin", "admin") as session:
        yield session


@pytest.fixture()
def editor_session(live_app: LiveApp):
    with _login(live_app.base_url, "editor", "editorPass123") as session:
        yield session


@pytest.fixture()
def viewer_session(live_app: LiveApp):
    with _login(live_app.base_url, "viewer", "viewerPass123") as session:
        yield session
