"""Host metrics read directly from /proc and statvfs (no extra dependencies).

Every function returns ``None`` when a value cannot be read, so the UI can
show "unavailable" rather than a fabricated number.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_PROC = Path("/proc")


@dataclass
class HostMetrics:
    cpu_percent: float | None
    load_average: list[float] | None
    cpu_count: int | None
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    memory_percent: float | None
    disk_path: str
    disk_total_bytes: int | None
    disk_free_bytes: int | None
    disk_percent: float | None
    uptime_seconds: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cpu_times() -> tuple[int, int] | None:
    try:
        fields = (_PROC / "stat").read_text().splitlines()[0].split()[1:]
        values = [int(v) for v in fields]
    except (OSError, ValueError, IndexError):
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return idle, sum(values)


def cpu_percent(interval: float = 0.2) -> float | None:
    first = _cpu_times()
    if first is None:
        return None
    time.sleep(interval)
    second = _cpu_times()
    if second is None:
        return None
    idle, total = second[0] - first[0], second[1] - first[1]
    if total <= 0:
        return None
    return round(100.0 * (1 - idle / total), 1)


def memory() -> tuple[int | None, int | None]:
    try:
        info = {}
        for line in (_PROC / "meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.strip().split()[0]) * 1024
        return info.get("MemTotal"), info.get("MemAvailable")
    except (OSError, ValueError, IndexError):
        return None, None


def uptime() -> float | None:
    try:
        return float((_PROC / "uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def collect(disk_path: str = "/") -> HostMetrics:
    total_mem, avail_mem = memory()
    disk_total: int | None
    disk_free: int | None
    try:
        st = os.statvfs(disk_path)
        disk_total = st.f_blocks * st.f_frsize
        disk_free = st.f_bavail * st.f_frsize
    except OSError:
        disk_total = disk_free = None
    try:
        load = list(os.getloadavg())
    except OSError:
        load = None
    return HostMetrics(
        cpu_percent=cpu_percent(),
        load_average=[round(v, 2) for v in load] if load else None,
        cpu_count=os.cpu_count(),
        memory_total_bytes=total_mem,
        memory_available_bytes=avail_mem,
        memory_percent=round(100 * (1 - avail_mem / total_mem), 1)
        if total_mem and avail_mem is not None
        else None,
        disk_path=disk_path,
        disk_total_bytes=disk_total,
        disk_free_bytes=disk_free,
        disk_percent=round(100 * (1 - disk_free / disk_total), 1)
        if disk_total and disk_free is not None
        else None,
        uptime_seconds=uptime(),
    )
