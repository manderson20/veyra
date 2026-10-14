# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turning a message into the request a clock accepts, and sending it.

AND publishes no inbound API for third-party senders; the clock's own web
page posts messages to the device. The administrator describes that request
once (method, path, body template, sign-in) and Veyra fills it in for every
clock. Formatting uses AND's inline markup (application note AN049, "Allow
inline text commands" must be on in the clock) and, for {xml}, the
IPSpeakerMessage format of application note AN050.
"""

from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, quote_plus
from xml.sax.saxutils import quoteattr

import httpx

COLORS = ("default", "red", "green", "yellow", "orange", "gold")
PRIORITIES = {"normal": 50, "high": 20, "emergency": 1}
FLASHERS = {"off": "", "slow": "SSS", "fast": "FFF", "on": "111"}
CONTENT_TYPES = {
    "form": "application/x-www-form-urlencoded",
    "xml": "application/xml",
    "json": "application/json",
    "text": "text/plain; charset=utf-8",
    "none": "",
}
PLACEHOLDERS = ("text", "plain_text", "xml", "color", "seconds", "priority", "flashers", "password")


@dataclass(frozen=True)
class Message:
    text: str
    color: str = "default"
    seconds: int = 60
    priority: str = "normal"
    flashers: str = "off"


@dataclass(frozen=True)
class Delivery:
    method: str
    scheme: str
    path: str
    content_type: str
    body: str
    auth: str
    username: str
    password: str


@dataclass(frozen=True)
class Outcome:
    clock: str
    ok: bool
    detail: str


def marked_up(msg: Message) -> str:
    """The message text with AND inline commands for colour and flashers."""
    params = []
    if msg.color and msg.color != "default":
        params.append(f"color={msg.color}")
    if FLASHERS.get(msg.flashers):
        params.append(f"flashers={FLASHERS[msg.flashers]}")
    return ("{" + ";".join(params) + "}" if params else "") + msg.text


def ip_speaker_message(msg: Message) -> str:
    """An AN050 IPSpeakerMessage document for senders that take XML."""
    attrs = [f"text={quoteattr(msg.text)}", f"prio={quoteattr(str(PRIORITIES[msg.priority]))}"]
    if msg.color != "default":
        attrs.append(f"color={quoteattr(msg.color)}")
    if msg.seconds > 0:
        attrs += ['loops="0"', f"maxseconds={quoteattr(str(msg.seconds))}"]
    if FLASHERS.get(msg.flashers):
        attrs.append(f"setflashers_val={quoteattr(FLASHERS[msg.flashers])}")
    return "<IPSpeakerMessage><Message " + " ".join(attrs) + " /></IPSpeakerMessage>"


def values(msg: Message, delivery: Delivery) -> dict[str, str]:
    return {
        "text": marked_up(msg),
        "plain_text": msg.text,
        "xml": ip_speaker_message(msg),
        "color": "" if msg.color == "default" else msg.color,
        "seconds": str(msg.seconds),
        "priority": str(PRIORITIES[msg.priority]),
        "flashers": FLASHERS.get(msg.flashers, ""),
        "password": delivery.password,
    }


def fill(template: str, vals: dict[str, str], escape: Any) -> str:
    """Replace {name} placeholders only; other braces (AND markup in a
    template) are left alone."""
    out = template
    for key in PLACEHOLDERS:
        out = out.replace("{" + key + "}", escape(vals[key]))
    return out


def _json(v: str) -> str:
    return json.dumps(v)[1:-1]


def _xml(v: str) -> str:
    return quoteattr(v)[1:-1]


BODY_ESCAPES: dict[str, Any] = {
    "form": quote_plus,
    "json": _json,
    "xml": _xml,
    "text": lambda v: v,
    "none": lambda v: v,
}


def build_request(
    address: str, msg: Message, delivery: Delivery
) -> tuple[str, str, bytes, dict[str, str]]:
    """(method, url, body, headers) for one clock."""
    vals = values(msg, delivery)
    path = fill(delivery.path, vals, lambda v: quote(v, safe=""))
    if not path.startswith("/"):
        path = "/" + path
    url = f"{delivery.scheme}://{address}{path}"
    headers: dict[str, str] = {}
    body = b""
    if delivery.method == "POST" and delivery.content_type != "none":
        escape = BODY_ESCAPES[delivery.content_type]
        if delivery.content_type == "xml":
            # {xml} is a whole document: insert it as is, escape the rest.
            filled = delivery.body.replace("{xml}", "\x00XML\x00")
            filled = fill(filled, vals, escape).replace("\x00XML\x00", vals["xml"])
        else:
            filled = fill(delivery.body, vals, escape)
        body = filled.encode()
        headers["Content-Type"] = CONTENT_TYPES[delivery.content_type]
    return delivery.method, url, body, headers


def send_one(
    client: httpx.Client, name: str, address: str, msg: Message, delivery: Delivery
) -> Outcome:
    method, url, body, headers = build_request(address, msg, delivery)
    auth: httpx.Auth | None = None
    if delivery.auth == "basic":
        auth = httpx.BasicAuth(delivery.username, delivery.password)
    elif delivery.auth == "digest":
        auth = httpx.DigestAuth(delivery.username, delivery.password)
    try:
        r = client.request(method, url, content=body or None, headers=headers, auth=auth)
    except httpx.HTTPError as e:
        return Outcome(name, False, f"{type(e).__name__}: {e}"[:300])
    if r.status_code >= 400:
        return Outcome(name, False, f"HTTP {r.status_code}")
    return Outcome(name, True, f"HTTP {r.status_code}")


def send(
    clocks: list[tuple[str, str]], msg: Message, delivery: Delivery, timeout: float
) -> list[Outcome]:
    """Send to every (name, address) in parallel. Clocks use self-signed
    certificates, so https does not verify them (the network is local)."""
    if not clocks:
        return []
    with (
        httpx.Client(timeout=timeout, verify=False, follow_redirects=False) as client,  # noqa: S501
        ThreadPoolExecutor(max_workers=min(16, len(clocks))) as pool,
    ):
        return list(pool.map(lambda c: send_one(client, c[0], c[1], msg, delivery), clocks))


def split_address(address: str, default_port: int) -> tuple[str, int]:
    host, sep, port = address.rpartition(":")
    if sep and port.isdigit() and not host.endswith(":"):
        return host.strip("[]"), int(port)
    return address.strip("[]"), default_port


def reachable(address: str, port: int, timeout: float) -> bool:
    host, p = split_address(address, port)
    try:
        with socket.create_connection((host, p), timeout=timeout):
            return True
    except OSError:
        return False
