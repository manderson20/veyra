# SPDX-License-Identifier: AGPL-3.0-or-later
"""Client of the HA agent's socket (docs/HIGH_AVAILABILITY.md §3): one JSON
request per connection, one JSON answer. Used by the API and the CLI; the
agent itself is in :mod:`veyra.ha.agent`.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

SOCKET_PATH = Path("/run/veyra/ha.sock")
MAX_LINE = 4 * 1024 * 1024


class AgentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class AgentUnavailable(AgentError):
    def __init__(self, message: str = "The HA agent is not running.") -> None:
        super().__init__("agent_unavailable", message)


def encode_request(verb: str, args: dict[str, Any]) -> bytes:
    return json.dumps({"verb": verb, "args": args}, separators=(",", ":")).encode() + b"\n"


def decode_answer(line: bytes) -> Any:
    try:
        data = json.loads(line)
    except ValueError as e:
        raise AgentError("bad_answer", "The agent's answer is not JSON.") from e
    if not isinstance(data, dict):
        raise AgentError("bad_answer", "The agent's answer is not an object.")
    if not data.get("ok"):
        raise AgentError(str(data.get("code") or "agent_error"), str(data.get("error") or "failed"))
    return data.get("result")


class AgentClient:
    def __init__(self, path: Path = SOCKET_PATH, timeout: float = 30.0) -> None:
        self.path, self.timeout = path, timeout

    def call(self, verb: str, **args: Any) -> Any:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect(str(self.path))
                s.sendall(encode_request(verb, args))
                s.shutdown(socket.SHUT_WR)
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_LINE:
                        raise AgentError("bad_answer", "The agent's answer is too large.")
        except (OSError, TimeoutError) as e:
            raise AgentUnavailable(f"The HA agent is not reachable: {e}") from e
        return decode_answer(b"".join(chunks))

    def available(self) -> bool:
        return self.path.exists()
