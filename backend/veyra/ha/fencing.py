# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fencing through the Proxmox VE API (docs/HIGH_AVAILABILITY.md §7.2): stop
the other node's VM and wait until it is stopped. The only method in scope.
"""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass
from typing import Any

import httpx

TIMEOUT = 15.0
STOP_WAIT = 60.0
# Tests replace this with an httpx.MockTransport.
transport: httpx.BaseTransport | None = None


class FencingError(Exception):
    pass


@dataclass(frozen=True)
class ProxmoxTarget:
    url: str  # https://pve.example:8006
    token_id: str  # user@realm!name
    token_secret: str
    pve_node: str
    vmid: int
    ca_pem: str | None = None
    verify_tls: bool = True


def settings_to_target(value: dict[str, Any], node_name: str, secret: str) -> ProxmoxTarget | None:
    """The target for ``node_name`` from the ``ha.fencing`` setting (secret
    decrypted by the caller)."""
    if not value.get("enabled") or value.get("method", "proxmox") != "proxmox":
        return None
    vms: dict[str, Any] = value["vms"] if isinstance(value.get("vms"), dict) else {}
    entry = vms.get(node_name)
    if not isinstance(entry, dict) or not entry.get("vmid"):
        return None
    return ProxmoxTarget(
        url=str(value.get("url") or "").rstrip("/"),
        token_id=str(value.get("token_id") or ""),
        token_secret=secret,
        pve_node=str(entry.get("pve_node") or value.get("pve_node") or ""),
        vmid=int(entry["vmid"]),
        ca_pem=value.get("ca_pem") or None,
        verify_tls=bool(value.get("verify_tls", True)),
    )


def _client(t: ProxmoxTarget) -> httpx.Client:
    verify: ssl.SSLContext | bool = t.verify_tls
    if t.ca_pem:
        verify = ssl.create_default_context(cadata=t.ca_pem)
    return httpx.Client(
        base_url=t.url,
        timeout=TIMEOUT,
        verify=verify,
        transport=transport,
        headers={"Authorization": f"PVEAPIToken={t.token_id}={t.token_secret}"},
    )


def vm_status(t: ProxmoxTarget) -> str:
    try:
        with _client(t) as c:
            r = c.get(f"/api2/json/nodes/{t.pve_node}/qemu/{t.vmid}/status/current")
    except httpx.HTTPError as e:
        raise FencingError(f"Proxmox is not reachable: {type(e).__name__}: {e}") from e
    if r.status_code != 200:
        raise FencingError(f"Proxmox answered {r.status_code} for the VM status")
    try:
        return str(r.json()["data"]["status"])
    except (ValueError, KeyError, TypeError) as e:
        raise FencingError("Proxmox's answer has no VM status") from e


def stop_vm(t: ProxmoxTarget, *, wait: float = STOP_WAIT, sleep: float = 2.0) -> str:
    """Hard-stop the VM and wait until Proxmox reports ``stopped``."""
    if vm_status(t) == "stopped":
        return "already stopped"
    try:
        with _client(t) as c:
            r = c.post(f"/api2/json/nodes/{t.pve_node}/qemu/{t.vmid}/status/stop")
    except httpx.HTTPError as e:
        raise FencingError(f"Proxmox is not reachable: {type(e).__name__}: {e}") from e
    if r.status_code != 200:
        raise FencingError(f"Proxmox refused the stop ({r.status_code}): {r.text[:200]}")
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if vm_status(t) == "stopped":
            return "stopped"
        time.sleep(sleep)
    raise FencingError(f"the VM did not stop within {int(wait)} seconds")


def check(t: ProxmoxTarget) -> dict[str, Any]:
    """Reachability and the VM's current state, for the HA page."""
    try:
        return {"ok": True, "status": vm_status(t)}
    except FencingError as e:
        return {"ok": False, "error": str(e)}
