"""A minimal MCP client over stdio, just enough to drive mcp_server/server.py in tests: the
initialize handshake plus tools/call. Not a general-purpose MCP client - the real one is whatever
MCP host (Claude Code, Claude Desktop, ...) launches this server for actual use.

stdout and stderr are each drained by their own background thread into a queue. Reading a pipe
directly in the main thread deadlocks as soon as the child writes enough to fill the OS pipe
buffer while nobody is reading it (a real failure hit while writing this test, not a hypothetical:
readline() on stdout blocked forever because stderr had filled up and the child was stuck writing
to it). The reader threads make sure both pipes are always being drained, whatever the main
thread happens to be doing.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

MCP_SERVER_DIR = Path(__file__).resolve().parent.parent / "mcp_server"


class McpStdioSession:
    def __init__(self, base_url: str, username: str, password: str):
        env = {
            **os.environ,
            "CATALOG_BASE_URL": base_url,
            "CATALOG_USERNAME": username,
            "CATALOG_PASSWORD": password,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        self._process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=MCP_SERVER_DIR,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._stdout_lines: "queue.Queue[str | None]" = queue.Queue()
        self._stderr_lines: "queue.Queue[str | None]" = queue.Queue()
        self._stderr_tail: list[str] = []
        self._start_reader(self._process.stdout, self._stdout_lines)
        self._start_reader(self._process.stderr, self._stderr_lines, tail=self._stderr_tail)

        self._next_id = 1
        self._initialize()

    @staticmethod
    def _start_reader(pipe, out_queue: "queue.Queue[str | None]", tail: list[str] | None = None) -> None:
        def _drain() -> None:
            for line in iter(pipe.readline, ""):
                if tail is not None:
                    tail.append(line)
                    if len(tail) > 200:
                        del tail[0]
                out_queue.put(line)
            out_queue.put(None)  # signals EOF

        threading.Thread(target=_drain, daemon=True).start()

    def _write(self, message: dict) -> None:
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def _read_response(self, want_id: int, timeout: float = 15.0) -> dict:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self._stdout_lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:  # stdout closed - the process died
                break
            line = line.strip()
            if not line:
                continue
            message = json.loads(line)
            if message.get("id") == want_id:
                return message
        raise TimeoutError(
            f"no response with id={want_id} from mcp_server within {timeout}s; "
            f"recent stderr:\n{''.join(self._stderr_tail[-40:])}"
        )

    def _initialize(self) -> None:
        request_id = self._next_id
        self._next_id += 1
        self._write({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest-mcp-stdio", "version": "0"},
            },
        })
        response = self._read_response(request_id)
        if "error" in response:
            raise RuntimeError(f"initialize failed: {response['error']}")
        self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})

    # Tools whose Python return type is a list. The MCP SDK's _convert_to_content unrolls a
    # list/tuple return into one content block per item instead of one block holding a JSON
    # array, so parsing has to know up front whether to expect that shape - a single matching
    # tool would otherwise look identical, on the wire, to a dict-returning tool.
    _LIST_RESULT_TOOLS = frozenset({"list_tools"})

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        """Calls an MCP tool and returns its parsed JSON content, or raises RuntimeError with the
        MCP-level error if the call itself (not the underlying app request) failed."""
        request_id = self._next_id
        self._next_id += 1
        self._write({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        response = self._read_response(request_id)
        if "error" in response:
            raise RuntimeError(f"{name} failed at the MCP layer: {response['error']}")
        content = response["result"].get("content", [])

        def _parse(text: str) -> Any:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

        if name in self._LIST_RESULT_TOOLS:
            return [_parse(block["text"]) for block in content]

        if not content:
            return None
        return _parse(content[0]["text"])

    def close(self) -> None:
        try:
            self._process.stdin.close()
        except OSError:
            pass
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
