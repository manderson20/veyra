# SPDX-License-Identifier: AGPL-3.0-or-later
"""PostgreSQL replication for the HA pair (docs/HIGH_AVAILABILITY.md §4.1):
the configuration fragment, the managed ``pg_hba.conf`` block, replication
figures, and the commands the agent runs as the ``postgres`` user.

Everything that touches the system goes through a :class:`Runner` so the
sequences are testable without a cluster.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONF_NAME = "veyra-ha.conf"
HBA_BEGIN = "# BEGIN veyra-ha (managed by Veyra; do not edit this block)"
HBA_END = "# END veyra-ha"
REPLICATION_ROLE = "veyra_replication"
SLOT_PREFIX = "veyra_"
MAX_SLOT_WAL = "4GB"


class PostgresError(RuntimeError):
    pass


# ----------------------------------------------------------------- fragments


def render_conf(
    *,
    node_address: str,
    cert_file: str,
    key_file: str,
    ca_file: str,
    synchronous_standby: str | None = None,
) -> str:
    """``conf.d/veyra-ha.conf`` (the same on both nodes, so a standby is ready
    to be promoted)."""
    lines = [
        "# Managed by Veyra (docs/HIGH_AVAILABILITY.md §4.1). Do not edit; the",
        "# HA agent rewrites this file.",
        f"listen_addresses = 'localhost,{node_address}'",
        "wal_level = replica",
        "wal_log_hints = on",
        "max_wal_senders = 5",
        "max_replication_slots = 5",
        f"max_slot_wal_keep_size = {MAX_SLOT_WAL}",
        "hot_standby = on",
        "hot_standby_feedback = on",
        "ssl = on",
        f"ssl_cert_file = '{cert_file}'",
        f"ssl_key_file = '{key_file}'",
        f"ssl_ca_file = '{ca_file}'",
    ]
    if synchronous_standby:
        lines.append(f"synchronous_standby_names = '{synchronous_standby}'")
        lines.append("synchronous_commit = on")
    else:
        lines.append("synchronous_standby_names = ''")
    return "\n".join(lines) + "\n"


def hba_lines(peers: Sequence[tuple[str, str]], database: str) -> list[str]:
    """One pair of lines per (name, address): replication for the standby and
    the database itself for ``pg_rewind``."""
    out: list[str] = []
    for name, address in peers:
        mask = "/128" if ":" in address else "/32"
        for db in ("replication", database):
            out.append(f"hostssl {db} {REPLICATION_ROLE} {address}{mask} scram-sha-256  # {name}")
    return out


def update_hba(text: str, lines: Sequence[str]) -> str:
    """``pg_hba.conf`` with the managed block replaced (or added at the top,
    before the distribution's rules, because the first matching line wins)."""
    block = "\n".join([HBA_BEGIN, *lines, HBA_END]) + "\n" if lines else ""
    pattern = re.compile(re.escape(HBA_BEGIN) + r".*?" + re.escape(HBA_END) + r"\n?", re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _m: block, text, count=1)
    return block + text


def hba_block(text: str) -> list[str]:
    m = re.search(re.escape(HBA_BEGIN) + r"\n(.*?)" + re.escape(HBA_END), text, re.DOTALL)
    return [ln for ln in m.group(1).splitlines() if ln.strip()] if m else []


def slot_name(node_name: str) -> str:
    """``veyra_<node>`` with only ``[a-z0-9_]``; idempotent on a slot name."""
    safe = re.sub(r"[^a-z0-9_]", "_", node_name.lower())
    if safe.startswith(SLOT_PREFIX):
        return safe[:63]
    return (SLOT_PREFIX + safe)[:63]


# ----------------------------------------------------------------- figures


def parse_lsn(value: str | None) -> int | None:
    """``X/Y`` to a byte position."""
    if not value or "/" not in value:
        return None
    hi, lo = value.split("/", 1)
    try:
        return (int(hi, 16) << 32) + int(lo, 16)
    except ValueError:
        return None


def lag_bytes(ahead: str | None, behind: str | None) -> int | None:
    a, b = parse_lsn(ahead), parse_lsn(behind)
    return None if a is None or b is None else max(a - b, 0)


@dataclass
class Replication:
    """What ``GET /ha/status`` shows under ``replication``."""

    db_role: str = "unknown"  # primary | standby | down
    state: str | None = None  # streaming | catchup | startup | ... (primary's view)
    receiver: str | None = None  # standby: streaming | stopped
    slot: str | None = None
    lag_bytes: int | None = None
    lag_seconds: float | None = None
    current_lsn: str | None = None
    replay_lsn: str | None = None
    replay_at: str | None = None
    synchronous: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_role": self.db_role,
            "state": self.state,
            "receiver": self.receiver,
            "slot": self.slot,
            "lag_bytes": self.lag_bytes,
            "lag_seconds": self.lag_seconds,
            "current_lsn": self.current_lsn,
            "replay_lsn": self.replay_lsn,
            "replay_at": self.replay_at,
            "synchronous": self.synchronous,
            "detail": self.detail,
        }


PRIMARY_SQL = (
    "SELECT application_name, state, sync_state, pg_current_wal_lsn()::text, "
    "replay_lsn::text, extract(epoch from replay_lag) FROM pg_stat_replication"
)
STANDBY_SQL = (
    "SELECT pg_last_wal_receive_lsn()::text, pg_last_wal_replay_lsn()::text, "
    "pg_last_xact_replay_timestamp()::text, "
    "(SELECT status FROM pg_stat_wal_receiver LIMIT 1), "
    "(SELECT slot_name FROM pg_stat_wal_receiver LIMIT 1)"
)


def replication_from_rows(
    in_recovery: bool, rows: Sequence[Sequence[Any]], slot: str | None = None
) -> Replication:
    """Build the figures from the rows of PRIMARY_SQL (not in recovery) or
    STANDBY_SQL (in recovery)."""
    if not in_recovery:
        r = Replication(db_role="primary", slot=slot)
        if not rows:
            r.state = None
            r.detail = "no standby connected"
            return r
        row = rows[0]
        r.state = str(row[1]) if row[1] else None
        r.synchronous = str(row[2] or "") in ("sync", "quorum")
        r.current_lsn = row[3]
        r.replay_lsn = row[4]
        r.lag_bytes = lag_bytes(row[3], row[4])
        r.lag_seconds = float(row[5]) if row[5] is not None else None
        return r
    r = Replication(db_role="standby")
    if rows:
        row = rows[0]
        r.current_lsn = row[0]
        r.replay_lsn = row[1]
        r.replay_at = row[2]
        r.receiver = str(row[3]) if row[3] else "stopped"
        r.slot = row[4] or slot
        r.state = "streaming" if r.receiver == "streaming" else None
        r.lag_bytes = lag_bytes(row[0], row[1])
    return r


# ----------------------------------------------------------------- commands


@dataclass
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str]], Result]


def subprocess_runner(timeout: float = 600) -> Runner:
    def run(argv: Sequence[str]) -> Result:
        try:
            p = subprocess.run(  # noqa: S603 - fixed argv built by the agent
                list(argv), capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return Result(127, "", str(e))
        return Result(p.returncode, p.stdout, p.stderr)

    return run


@dataclass
class Cluster:
    """The Debian cluster (``pg_lsclusters``): version, name, data directory."""

    version: str
    name: str
    data_dir: Path
    port: int = 5432

    @property
    def conf_dir(self) -> Path:
        return Path("/etc/postgresql") / self.version / self.name

    @property
    def conf_d(self) -> Path:
        return self.conf_dir / "conf.d"

    @property
    def hba_path(self) -> Path:
        return self.conf_dir / "pg_hba.conf"

    @property
    def bin_dir(self) -> Path:
        return Path("/usr/lib/postgresql") / self.version / "bin"


def parse_lsclusters(text: str) -> Cluster | None:
    """The first cluster of ``pg_lsclusters --no-header``."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[0].isdigit():
            return Cluster(parts[0], parts[1], Path(parts[5]), int(parts[2]))
    return None


@dataclass
class Postgres:
    """The agent's handle on the local cluster."""

    cluster: Cluster
    run: Runner = field(default_factory=subprocess_runner)
    database: str = "veyra"

    def _pg(self, *args: str) -> Result:
        return self.run(["runuser", "-u", "postgres", "--", *args])

    def sql(self, statement: str, *, database: str | None = None) -> Result:
        return self._pg(
            "psql", "-X", "-qtA", "-F", "\t", "-d", database or self.database, "-c", statement
        )

    def in_recovery(self) -> bool | None:
        r = self.sql("SELECT pg_is_in_recovery()")
        if not r.ok:
            return None
        return r.stdout.strip() == "t"

    def rows(self, statement: str) -> list[list[str | None]]:
        r = self.sql(statement)
        if not r.ok:
            raise PostgresError(r.stderr.strip() or "query failed")
        return [
            [c if c != "" else None for c in line.split("\t")]
            for line in r.stdout.splitlines()
            if line.strip()
        ]

    def replication(self, slot: str | None = None) -> Replication:
        rec = self.in_recovery()
        if rec is None:
            return Replication(db_role="down", detail="PostgreSQL is not answering")
        try:
            rows = self.rows(STANDBY_SQL if rec else PRIMARY_SQL)
        except PostgresError as e:
            return Replication(db_role="standby" if rec else "primary", detail=str(e))
        return replication_from_rows(rec, rows, slot)

    def current_lsn(self) -> str | None:
        rec = self.in_recovery()
        if rec is None:
            return None
        rows = self.rows(
            "SELECT pg_last_wal_replay_lsn()::text" if rec else "SELECT pg_current_wal_lsn()::text"
        )
        return rows[0][0] if rows and rows[0] else None

    def checkpoint(self) -> Result:
        return self.sql("CHECKPOINT")

    def ensure_replication_role(self, password: str) -> Result:
        # The password is generated by the agent (urlsafe characters only);
        # psql has no parameters, so it is quoted by hand.
        quoted = password.replace("'", "''")
        statement = (
            "DO $$ BEGIN "  # noqa: S608
            f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{REPLICATION_ROLE}') THEN "
            f"CREATE ROLE {REPLICATION_ROLE} REPLICATION LOGIN PASSWORD '{quoted}'; "
            f"ELSE ALTER ROLE {REPLICATION_ROLE} WITH REPLICATION LOGIN PASSWORD '{quoted}'; "
            "END IF; END $$"
        )
        return self.sql(statement, database="postgres")

    def grant_monitor(self, role: str) -> Result:
        return self.sql(f"GRANT pg_monitor TO {role}", database="postgres")

    def ensure_slot(self, slot: str) -> Result:
        slot = slot_name(slot)  # only [a-z0-9_]
        statement = (
            f"SELECT pg_create_physical_replication_slot('{slot}') WHERE NOT EXISTS "  # noqa: S608
            f"(SELECT 1 FROM pg_replication_slots WHERE slot_name = '{slot}')"
        )
        return self.sql(statement, database="postgres")

    def drop_slot(self, slot: str) -> Result:
        slot = slot_name(slot)
        statement = (
            f"SELECT pg_drop_replication_slot('{slot}') WHERE EXISTS "  # noqa: S608
            f"(SELECT 1 FROM pg_replication_slots WHERE slot_name = '{slot}')"
        )
        return self.sql(statement, database="postgres")

    def ctl(self, verb: str) -> Result:
        return self.run(["pg_ctlcluster", self.cluster.version, self.cluster.name, verb])

    @property
    def unit(self) -> str:
        return f"postgresql@{self.cluster.version}-{self.cluster.name}"

    def start(self) -> Result:
        return self.run(["systemctl", "start", self.unit])

    def stop(self) -> Result:
        return self.run(["systemctl", "stop", self.unit])

    def reload(self) -> Result:
        return self.ctl("reload")

    def promote(self) -> Result:
        return self.ctl("promote")

    def is_running(self) -> bool:
        r = self.run(["pg_ctlcluster", self.cluster.version, self.cluster.name, "status"])
        return r.ok

    def conninfo(self, host: str, password: str, ca_file: str) -> str:
        return (
            f"host={host} port={self.cluster.port} user={REPLICATION_ROLE} "
            f"password={password} sslmode=verify-ca sslrootcert={ca_file}"
        )

    def basebackup(self, host: str, password: str, ca_file: str, slot: str) -> Result:
        """Replace the data directory with a base backup of ``host`` and make
        it a standby of it (``-R`` writes ``primary_conninfo`` and ``standby.signal``)."""
        data = str(self.cluster.data_dir)
        self.stop()
        r = self.run(["rm", "-rf", "--one-file-system", data])
        if not r.ok:
            return r
        r = self.run(["install", "-d", "-o", "postgres", "-g", "postgres", "-m", "0700", data])
        if not r.ok:
            return r
        return self._pg(
            str(self.cluster.bin_dir / "pg_basebackup"),
            "-D",
            data,
            "-d",
            self.conninfo(host, password, ca_file),
            "-R",
            "-S",
            slot,
            "--checkpoint=fast",
            "-X",
            "stream",
            "--no-password",
        )

    def rewind(self, host: str, password: str, ca_file: str) -> Result:
        """Resynchronise a former primary with the new one; needs the cluster
        stopped cleanly and ``wal_log_hints``."""
        return self._pg(
            str(self.cluster.bin_dir / "pg_rewind"),
            "--target-pgdata",
            str(self.cluster.data_dir),
            "--source-server",
            self.conninfo(host, password, ca_file) + f" dbname={self.database}",
            "--restore-target-wal",
            "--no-ensure-shutdown",
        )

    def write_standby(self, host: str, password: str, ca_file: str, slot: str) -> None:
        """``postgresql.auto.conf`` lines and ``standby.signal`` after a rewind."""
        auto = self.cluster.data_dir / "postgresql.auto.conf"
        keep = [
            ln
            for ln in (auto.read_text().splitlines() if auto.exists() else [])
            if not ln.startswith(("primary_conninfo", "primary_slot_name"))
        ]
        keep.append(f"primary_conninfo = '{self.conninfo(host, password, ca_file)}'")
        keep.append(f"primary_slot_name = '{slot}'")
        auto.write_text("\n".join(keep) + "\n")
        signal = self.cluster.data_dir / "standby.signal"
        signal.touch()
        self.run(["chown", "postgres:postgres", str(auto), str(signal)])

    def clear_standby(self) -> None:
        signal = self.cluster.data_dir / "standby.signal"
        if signal.exists():
            signal.unlink()
