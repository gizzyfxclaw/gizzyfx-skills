"""chromedevtools_mcp_client.py — Client for the chrome-devtools MCP server.

The chrome-devtools MCP server is a stdio-based MCP server that controls a
Chrome browser instance. This client launches it as a subprocess and
communicates via JSON-RPC 2.0 over stdin/stdout.

Usage:
    from chromedevtools_mcp_client import ChromeDevToolsClient
    c = ChromeDevToolsClient()
    c.navigate("https://www.tradingview.com/chart/?symbol=OANDA:EURUSD")
    c.execute_js("document.title")
    c.screenshot("/tmp/chart.png")

Environment:
    CHROME_DEVTOOLS_SERVER (path to server.py, default /home/ubuntu/chrome-devtools-mcp/server.py)
    CHROME_PATH (optional, path to Chrome binary)
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Any

CHROME_DEVTOOLS_SERVER = os.environ.get(
    "CHROME_DEVTOOLS_SERVER", "/home/ubuntu/chrome-devtools-mcp/server.py"
)


class ChromeDevToolsClient:
    def __init__(self, server_path: str = CHROME_DEVTOOLS_SERVER):
        self.server_path = server_path
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the chrome-devtools MCP server subprocess."""
        if self.proc is not None:
            return
        env = os.environ.copy()
        self.proc = subprocess.Popen(
            ["/home/ubuntu/.hermes/hermes-agent/venv/bin/python", self.server_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        # Wait for server to be ready
        time.sleep(2)

    def stop(self) -> None:
        """Stop the server subprocess."""
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            self.proc = None

    def _next_id(self) -> int:
        with self._lock:
            self._id += 1
            return self._id

    def _send(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC 2.0 request and return the response."""
        if self.proc is None:
            self.start()
        req_id = self._next_id()
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            payload["params"] = params
        line = json.dumps(payload) + "\n"
        self.proc.stdin.write(line.encode())
        self.proc.stdin.flush()
        # Read response line
        while True:
            resp_line = self.proc.stdout.readline().decode().strip()
            if not resp_line:
                continue
            try:
                resp = json.loads(resp_line)
                if resp.get("id") == req_id:
                    return resp
            except json.JSONDecodeError:
                continue

    def call(self, tool_name: str, **arguments) -> dict:
        """Call an MCP tool by name."""
        return self._send("tools/call", {"name": tool_name, "arguments": arguments})

    # ---------- convenience methods ----------

    def navigate(self, url: str) -> dict:
        return self.call("navigate_to_url", url=url)

    def execute_js(self, expression: str) -> dict:
        return self.call("execute_javascript", expression=expression)

    def screenshot(self, path: str | None = None) -> dict:
        params = {}
        if path:
            params["path"] = path
        return self.call("capture_screenshot", **params)

    def describe_element(self, selector: str) -> dict:
        return self.call("describe_element", selector=selector)

    def evaluate_in_all_frames(self, expression: str) -> dict:
        return self.call("evaluate_in_all_frames", expression=expression)

    def get_document(self, depth: int = 3) -> dict:
        return self.call("get_document", depth=depth)

    def get_element_at_position(self, x: int, y: int) -> dict:
        return self.call("get_element_at_position", x=x, y=y)

    def get_computed_styles(self, selector: str) -> dict:
        return self.call("get_computed_styles", selector=selector)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


if __name__ == "__main__":
    import sys
    c = ChromeDevToolsClient()
    c.start()
    print(c.navigate("https://example.com"))
    print(c.execute_js("document.title"))
    c.stop()
