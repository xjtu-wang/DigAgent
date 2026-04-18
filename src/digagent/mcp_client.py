from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

from digagent.config import AppSettings
from digagent.mcp_models import McpServerManifest

JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"
STDERR_TAIL_LIMIT = 40


class McpClientError(RuntimeError):
    pass


class McpStdioClient:
    def __init__(self, settings: AppSettings, manifest: McpServerManifest) -> None:
        self.settings = settings
        self.manifest = manifest
        self._closed = False
        self._initialized = False
        self._request_id = 0
        self._process: subprocess.Popen[bytes] | None = None
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._stderr_tail: deque[str] = deque(maxlen=STDERR_TAIL_LIMIT)
        self._launch_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def initialize(self) -> dict[str, Any]:
        if self._initialized:
            return {}
        self._ensure_started()
        result = self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "clientInfo": {"name": "digagent", "version": "1.0.0"},
                "capabilities": {},
            },
        )
        self._send_notification("notifications/initialized", {})
        self._initialized = True
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        result = self.request("tools/list", {})
        tools = result.get("tools", [])
        return tools if isinstance(tools, list) else []

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.initialize()
        return self.request("tools/call", {"name": tool_name, "arguments": arguments})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._request_lock:
            self._ensure_started()
            request_id = self._next_request_id()
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            with self._pending_lock:
                self._pending[request_id] = response_queue
            try:
                self._send_message({"jsonrpc": JSONRPC_VERSION, "id": request_id, "method": method, "params": params})
                response = response_queue.get(timeout=self.settings.shell_timeout_sec)
            except queue.Empty as exc:
                raise McpClientError(f"MCP server '{self.manifest.server_id}' request timed out: {method}") from exc
            finally:
                with self._pending_lock:
                    self._pending.pop(request_id, None)
        error = response.get("error")
        if error:
            raise McpClientError(self._format_error(method, error))
        result = response.get("result")
        return result if isinstance(result, dict) else {"value": result}

    def close(self) -> None:
        self._closed = True
        self._initialized = False
        process = self._process
        if process is None:
            return
        if process.stdin:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._process = None

    def _ensure_started(self) -> None:
        if self._closed:
            raise McpClientError(f"MCP server '{self.manifest.server_id}' client is closed")
        process = self._process
        if process and process.poll() is None:
            return
        with self._launch_lock:
            process = self._process
            if process and process.poll() is None:
                return
            self._start_process()

    def _start_process(self) -> None:
        transport = self.manifest.transport
        command = [transport.command, *transport.args]
        cwd = self._resolve_cwd(transport.cwd)
        env = os.environ.copy()
        env.update({key: str(value) for key, value in transport.env.items()})
        self._initialized = False
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=env,
        )
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self._reader_thread.start()
        self._stderr_thread.start()

    def _resolve_cwd(self, cwd: str | None) -> Path | None:
        if not cwd:
            return None
        path = Path(cwd)
        return path if path.is_absolute() else (self.settings.workspace_root / path).resolve()

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        self._send_message({"jsonrpc": JSONRPC_VERSION, "method": method, "params": params})

    def _send_message(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise McpClientError(f"MCP server '{self.manifest.server_id}' is not running")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        process.stdin.write(header + body)
        process.stdin.flush()

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while True:
                message = self._read_message(process.stdout)
                if message is None:
                    break
                self._dispatch_message(message)
        except Exception as exc:  # pragma: no cover - surfaced through pending request failures
            self._fail_pending(str(exc))
            return
        self._fail_pending(self._exit_reason())

    def _stderr_loop(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = process.stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                self._stderr_tail.append(text)

    def _read_message(self, stream) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = stream.readline()
            if not line:
                return None
            if line in {b"\r\n", b"\n"}:
                break
            key, _, value = line.decode("ascii", errors="replace").partition(":")
            headers[key.strip().lower()] = value.strip()
        if "content-length" not in headers:
            raise McpClientError("missing Content-Length header")
        content_length = int(headers["content-length"])
        payload = stream.read(content_length)
        if len(payload) != content_length:
            raise McpClientError("incomplete MCP response body")
        return json.loads(payload.decode("utf-8"))

    def _dispatch_message(self, message: dict[str, Any]) -> None:
        response_id = message.get("id")
        if response_id is None:
            return
        with self._pending_lock:
            response_queue = self._pending.get(int(response_id))
        if response_queue is not None:
            try:
                response_queue.put_nowait(message)
            except queue.Full:
                return

    def _fail_pending(self, reason: str) -> None:
        failure = {"error": {"message": reason}}
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for response_queue in pending:
            try:
                response_queue.put_nowait(failure)
            except queue.Full:
                continue

    def _exit_reason(self) -> str:
        process = self._process
        exit_code = process.poll() if process else None
        stderr = " | ".join(self._stderr_tail)
        suffix = f"；stderr: {stderr}" if stderr else ""
        return f"MCP server '{self.manifest.server_id}' exited with code {exit_code}{suffix}"

    def _format_error(self, method: str, error: dict[str, Any]) -> str:
        message = str(error.get("message") or error)
        stderr = " | ".join(self._stderr_tail)
        if stderr:
            return f"MCP server '{self.manifest.server_id}' {method} failed: {message}；stderr: {stderr}"
        return f"MCP server '{self.manifest.server_id}' {method} failed: {message}"
