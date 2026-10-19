# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fax (docs/USER_PORTAL.md §9): a user's PDF becomes a fax TIFF with
Ghostscript and a queued job; the worker starts the job through the engine
(a Local channel over the organization's outbound routes, SendFAX once it
answers); the engine reports with ``UserEvent(VeyraFax)`` or a hung-up
channel; a received fax becomes a PDF (tiff2pdf) emailed to the inbox's
recipients. Files live under ``<data>/fax/<org slug>/<job>.tiff|.pdf``."""

from __future__ import annotations

import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
import textwrap
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from veyra.core import mail, tenancy
from veyra.core.config import Settings
from veyra.core.errors import ProblemError
from veyra.core.models import (
    ClassOfService,
    Extension,
    FaxInbox,
    FaxJob,
    Installation,
    Organization,
    User,
)
from veyra.core.models.base import utcnow
from veyra.core.models.fax import ACTIVE_STATES
from veyra.telephony.adapter import EngineUnavailable, NotSupported

log = logging.getLogger(__name__)

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 50
# Attempts for a call that did not connect (busy, no answer, congestion);
# a fax that connected but failed is tried once more.
MAX_ATTEMPTS = 3
RETRY_DELAYS = (timedelta(minutes=2), timedelta(minutes=5))
# Dialling or sending without any report from the engine.
DIAL_TIMEOUT = timedelta(minutes=10)
GS_TIMEOUT = 180
# Q.850 causes worth another attempt: busy, no user responding, no answer,
# no circuit, temporary failure, switching equipment congestion.
RETRY_CAUSES = {17, 18, 19, 34, 41, 42}
_NUMBER_RE = re.compile(r"^\+?[0-9]{3,20}$")
_INBOX_FILE_RE = re.compile(r"^[a-z0-9-]{1,40}-[0-9.]{1,40}\.tiff$")


class FaxError(ValueError):
    """The file could not be turned into a fax (or back into a PDF)."""


class ToolMissing(FaxError):
    """Ghostscript or tiff2pdf is not installed on the server."""


def tools_available() -> dict[str, bool]:
    return {"gs": shutil.which("gs") is not None, "tiff2pdf": shutil.which("tiff2pdf") is not None}


def normalize_number(value: str) -> str:
    """Digits with an optional leading ``+``; '' when the value is not a number."""
    digits = re.sub(r"[\s().-]", "", value or "")
    return digits if _NUMBER_RE.match(digits) else ""


# ------------------------------------------------------------------- files


def tiff_pages(path: Path) -> int:
    """The number of images (IFDs) in a TIFF, read without a library: fax
    TIFFs are a few hundred kilobytes and the directory chain is tiny."""
    data = path.read_bytes()
    if len(data) < 8 or data[:2] not in (b"II", b"MM"):
        raise FaxError("not a TIFF file")
    bo = "<" if data[:2] == b"II" else ">"
    if struct.unpack(bo + "H", data[2:4])[0] != 42:
        raise FaxError("not a classic TIFF file")
    offset = struct.unpack(bo + "I", data[4:8])[0]
    seen: set[int] = set()
    n = 0
    while offset and offset not in seen and offset + 2 <= len(data):
        seen.add(offset)
        n += 1
        count = struct.unpack(bo + "H", data[offset : offset + 2])[0]
        nxt = offset + 2 + count * 12
        if nxt + 4 > len(data):
            break
        offset = struct.unpack(bo + "I", data[nxt : nxt + 4])[0]
    return n


def _ps_text(value: Any, limit: int = 200) -> str:
    """A string literal body for PostScript: ASCII only, parentheses and
    backslashes escaped, trimmed."""
    text = str(value or "")[:limit]
    text = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def cover_postscript(cover: dict[str, Any], *, pages: int, when: datetime) -> bytes:
    """A one-page letter cover sheet: To, From, Date, Pages, Subject, a note."""
    rows = [
        ("To", cover.get("to")),
        ("From", cover.get("from")),
        ("Date", when.strftime("%Y-%m-%d %H:%M UTC")),
        ("Pages", f"{pages + 1} (including this cover)"),
        ("Subject", cover.get("subject")),
    ]
    out = [
        "%!PS-Adobe-3.0",
        "%%Pages: 1",
        "%%Page: 1 1",
        "/Helvetica-Bold findfont 30 scalefont setfont",
        "72 700 moveto (FAX) show",
        "/Helvetica findfont 13 scalefont setfont",
        "72 690 moveto 540 690 lineto 2 setlinewidth stroke",
    ]
    y = 655
    for label, value in rows:
        if value is None or str(value).strip() == "":
            continue
        out.append("/Helvetica-Bold findfont 13 scalefont setfont")
        out.append(f"72 {y} moveto ({_ps_text(label)}) show")
        out.append("/Helvetica findfont 13 scalefont setfont")
        out.append(f"160 {y} moveto ({_ps_text(value, 80)}) show")
        y -= 22
    note = str(cover.get("note") or "").strip()
    if note:
        y -= 14
        out.append(f"72 {y} moveto 540 {y} lineto 1 setlinewidth stroke")
        y -= 26
        out.append("/Helvetica findfont 12 scalefont setfont")
        for paragraph in note.splitlines()[:40]:
            for line in textwrap.wrap(paragraph, 84) or [""]:
                if y < 72:
                    break
                out.append(f"72 {y} moveto ({_ps_text(line, 120)}) show")
                y -= 16
    out += ["showpage", "%%EOF", ""]
    return "\n".join(out).encode("ascii")


def _gs(inputs: list[str], out: Path) -> None:
    gs = shutil.which("gs")
    if gs is None:
        raise ToolMissing("Ghostscript (gs) is not installed on the server")
    cmd = [
        gs,
        "-q",
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        "-sDEVICE=tiffg4",
        "-r204x196",
        "-sPAPERSIZE=letter",
        "-dFIXEDMEDIA",
        "-dPDFFitPage",
        f"-sOutputFile={out}",
        *inputs,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=GS_TIMEOUT)  # noqa: S603 — fixed binary
    except subprocess.TimeoutExpired as e:
        raise FaxError("converting the PDF took too long") from e
    if proc.returncode != 0 or not out.exists():
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
        raise FaxError("the PDF could not be converted" + (f": {tail[0][:200]}" if tail else ""))


def _store(src: Path, dest: Path) -> None:
    """Move a file into the fax tree, readable by the engine (group asterisk)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with_group = os.stat(dest.parent)
    shutil.move(str(src), str(dest))
    os.chmod(dest, 0o660)
    with_suppress_chown(dest, with_group.st_gid)


def with_suppress_chown(path: Path, gid: int) -> None:
    try:
        os.chown(path, -1, gid)
    except OSError:
        pass


def render(pdf: bytes, cover: dict[str, Any] | None, dest: Path) -> int:
    """PDF (plus an optional cover sheet) → fax TIFF (G4, 204×196 dpi, letter)
    at ``dest``; returns the number of pages. Raises FaxError."""
    with tempfile.TemporaryDirectory(prefix="veyra-fax-") as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(pdf)
        out = Path(tmp) / "out.tiff"
        _gs([str(src)], out)
        pages = tiff_pages(out)
        if pages == 0:
            raise FaxError("the PDF has no pages")
        if cover:
            ps = Path(tmp) / "cover.ps"
            ps.write_bytes(cover_postscript(cover, pages=pages, when=utcnow()))
            out.unlink()
            _gs([str(ps), str(src)], out)
            pages += 1
        if pages > MAX_PAGES:
            raise FaxError(f"the fax has {pages} pages; the limit is {MAX_PAGES}")
        _store(out, dest)
        return pages


def to_pdf(tiff: Path, dest: Path) -> None:
    """A received TIFF → PDF with tiff2pdf (libtiff-tools)."""
    tool = shutil.which("tiff2pdf")
    if tool is None:
        raise ToolMissing("tiff2pdf (libtiff-tools) is not installed on the server")
    with tempfile.TemporaryDirectory(prefix="veyra-fax-") as tmp:
        out = Path(tmp) / "out.pdf"
        try:
            proc = subprocess.run(  # noqa: S603 — fixed binary
                [tool, "-o", str(out), str(tiff)], capture_output=True, timeout=GS_TIMEOUT
            )
        except subprocess.TimeoutExpired as e:
            raise FaxError("converting the fax took too long") from e
        if proc.returncode != 0 or not out.exists():
            raise FaxError("the received pages could not be converted to PDF")
        _store(out, dest)


def file_path(settings: Settings, relative: str | None) -> Path | None:
    if not relative:
        return None
    path = (settings.fax_dir / relative).resolve()
    if settings.fax_dir.resolve() not in path.parents:
        return None
    return path if path.is_file() else None


# ------------------------------------------------------------------- API shape


class JobOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    direction: str
    number: str
    caller_id: str | None
    remote_id: str | None
    pages: int
    state: str
    error: str | None
    attempts: int
    user_id: uuid.UUID | None
    user_name: str | None
    extension_number: str | None
    inbox_id: uuid.UUID | None
    inbox_name: str | None
    original_name: str | None
    has_cover: bool
    has_file: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    next_attempt_at: datetime | None


def outs(db: Session, rows: list[FaxJob]) -> list[JobOut]:
    user_ids = {r.user_id for r in rows if r.user_id}
    ext_ids = {r.extension_id for r in rows if r.extension_id}
    inbox_ids = {r.inbox_id for r in rows if r.inbox_id}
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
        if user_ids
        else {}
    )
    exts = (
        {e.id: e for e in db.scalars(select(Extension).where(Extension.id.in_(ext_ids)))}
        if ext_ids
        else {}
    )
    inboxes = (
        {i.id: i for i in db.scalars(select(FaxInbox).where(FaxInbox.id.in_(inbox_ids)))}
        if inbox_ids
        else {}
    )
    out = []
    for r in rows:
        user = users.get(r.user_id) if r.user_id else None
        ext = exts.get(r.extension_id) if r.extension_id else None
        inbox = inboxes.get(r.inbox_id) if r.inbox_id else None
        out.append(
            JobOut(
                id=r.id,
                organization_id=r.organization_id,
                direction=r.direction,
                number=r.number,
                caller_id=r.caller_id,
                remote_id=r.remote_id,
                pages=r.pages,
                state=r.state,
                error=r.error,
                attempts=r.attempts,
                user_id=r.user_id,
                user_name=user.display_name if user else None,
                extension_number=ext.number if ext else None,
                inbox_id=r.inbox_id,
                inbox_name=inbox.name if inbox else None,
                original_name=r.original_name,
                has_cover=bool(r.cover),
                has_file=bool(r.pdf_file or r.file),
                created_at=r.created_at,
                started_at=r.started_at,
                finished_at=r.finished_at,
                next_attempt_at=r.next_attempt_at,
            )
        )
    return out


# ------------------------------------------------------------------- sending


def check_may_fax(db: Session, extension: Extension) -> None:
    """The class of service may forbid faxing (docs/USER_PORTAL.md §9)."""
    if extension.class_of_service_id is None:
        return
    cos = db.get(ClassOfService, extension.class_of_service_id)
    if cos is not None and not cos.allow_fax:
        raise ProblemError(
            422,
            "Fax not allowed",
            "Your phone's class of service does not allow sending faxes; ask an administrator.",
            code="cos_denied",
        )


def create_outbound(
    db: Session,
    settings: Settings,
    *,
    user: User,
    extension: Extension,
    number: str,
    pdf: bytes,
    filename: str | None,
    cover: dict[str, Any] | None,
) -> FaxJob:
    """Validate, render and queue a fax; the worker sends it."""
    digits = normalize_number(number)
    if not digits:
        raise ProblemError(
            422,
            "Invalid number",
            "Enter the fax number as digits, with an optional leading +.",
            code="validation_failed",
            errors=[{"field": "number", "message": "digits only"}],
        )
    if not pdf:
        raise ProblemError(415, "Empty file", "The file is empty.", code="unsupported_file")
    if len(pdf) > MAX_PDF_BYTES:
        raise ProblemError(
            413, "File too large", f"The PDF may be up to {MAX_PDF_BYTES >> 20} MB.", code="too_large"
        )
    if not pdf.lstrip()[:5].startswith(b"%PDF-"):
        raise ProblemError(
            415, "Not a PDF", "Upload a PDF file; other formats are not faxed.", code="unsupported_file"
        )
    check_may_fax(db, extension)
    org = db.get(Organization, extension.organization_id)
    if org is None:
        raise ProblemError(409, "No organization", "The extension has no organization.", code="conflict")
    job = FaxJob(
        id=uuid.uuid4(),
        organization_id=org.id,
        user_id=user.id,
        extension_id=extension.id,
        direction="out",
        number=digits,
        caller_id=extension.outbound_caller_id_number or None,
        pages=0,
        state="queued",
        attempts=0,
        original_name=(filename or "")[:255] or None,
        cover=cover or None,
        next_attempt_at=utcnow(),
    )
    rel = f"{org.slug}/{job.id}"
    tiff = settings.fax_dir / f"{rel}.tiff"
    try:
        job.pages = render(pdf, cover, tiff)
    except ToolMissing as e:
        raise ProblemError(503, "Fax unavailable", str(e), code="fax_tools_missing") from e
    except FaxError as e:
        raise ProblemError(422, "Cannot fax this file", str(e), code="fax_render_failed") from e
    pdf_path = settings.fax_dir / f"{rel}.pdf"
    pdf_path.write_bytes(pdf)
    os.chmod(pdf_path, 0o660)
    job.file = f"{rel}.tiff"
    job.pdf_file = f"{rel}.pdf"
    db.add(job)
    db.flush()
    return job


def start_due(db: Session, settings: Settings, adapter: Any, now: datetime | None = None) -> int:
    """Originate the queued jobs whose time has come (worker tick)."""
    if adapter is None or not hasattr(adapter, "originate_channel"):
        return 0
    now = now or utcnow()
    jobs = db.scalars(
        select(FaxJob)
        .where(
            FaxJob.direction == "out",
            FaxJob.state == "queued",
            or_(FaxJob.next_attempt_at.is_(None), FaxJob.next_attempt_at <= now),
        )
        .order_by(FaxJob.created_at)
        .limit(5)
    ).all()
    started = 0
    for job in jobs:
        org = db.get(Organization, job.organization_id)
        tiff = file_path(settings, job.file)
        if org is None or tiff is None:
            job.state, job.error, job.finished_at = "failed", "The fax file is gone.", now
            continue
        names = tenancy.names_of(db, org.id)
        ext = db.get(Extension, job.extension_id) if job.extension_id else None
        cos = (
            db.get(ClassOfService, ext.class_of_service_id)
            if ext is not None and ext.class_of_service_id
            else None
        )
        variables = {
            "__VEYRA_FAX_JOB": str(job.id),
            "__VEYRA_FAX_FILE": str(tiff),
            "__VEYRA_FAX_NUMBER": job.number,
            "__VEYRA_FAX_HEADER": org.fax_header or "",
            "__VEYRA_FAX_STATION": org.fax_station_id or "",
            "__VEYRA_ORG": org.slug,
        }
        if job.caller_id:
            variables["__VEYRA_OUT_CID"] = job.caller_id
        if cos is not None:
            variables["__VEYRA_COS"] = cos.slug
        caller_id = f'"Fax" <{job.caller_id}>' if job.caller_id else "Fax"
        job.attempts += 1
        try:
            channel = adapter.originate_channel(
                f"Local/{job.number}@{names.outbound}/n",
                "send",
                context=names.fax_out,
                caller_id=caller_id,
                timeout=60,
                variables=variables,
            )
        except (EngineUnavailable, NotSupported) as e:
            _retry_or_fail(db, settings, job, f"The engine refused the call: {e}", now, MAX_ATTEMPTS)
            continue
        job.state = "dialling"
        job.channel_id = (channel or "")[:80] or None
        job.started_at = now
        job.error = None
        started += 1
    return started


def _retry_or_fail(
    db: Session, settings: Settings, job: FaxJob, error: str, now: datetime, max_attempts: int
) -> None:
    job.error = error[:2000]
    job.channel_id = None
    if job.attempts < max_attempts:
        delay = RETRY_DELAYS[min(max(job.attempts - 1, 0), len(RETRY_DELAYS) - 1)]
        job.state = "queued"
        job.next_attempt_at = now + delay
        return
    job.state = "failed"
    job.finished_at = now
    _notify_user(db, settings, job)


def expire(db: Session, settings: Settings, now: datetime | None = None) -> int:
    """Attempts the engine never reported on."""
    now = now or utcnow()
    n = 0
    for job in db.scalars(
        select(FaxJob).where(
            FaxJob.state.in_(("dialling", "sending")),
            FaxJob.started_at.is_not(None),
            FaxJob.started_at < now - DIAL_TIMEOUT,
        )
    ).all():
        _retry_or_fail(db, settings, job, "No report from the engine within 10 minutes.", now, MAX_ATTEMPTS)
        n += 1
    return n


def tick(db: Session, settings: Settings, adapter: Any) -> None:
    expire(db, settings)
    start_due(db, settings, adapter)


def cancel(db: Session, settings: Settings, job: FaxJob, now: datetime | None = None) -> None:
    if job.state not in ACTIVE_STATES:
        raise ProblemError(409, "Not active", "This fax is not waiting or in progress.", code="wrong_state")
    job.state = "cancelled"
    job.finished_at = now or utcnow()
    job.next_attempt_at = None


def retry(db: Session, settings: Settings, job: FaxJob, now: datetime | None = None) -> None:
    if job.direction != "out" or job.state not in ("failed", "cancelled"):
        raise ProblemError(409, "Cannot retry", "Only failed or cancelled sends can be retried.", code="wrong_state")
    if file_path(settings, job.file) is None:
        raise ProblemError(409, "File gone", "The fax file was removed by retention.", code="file_gone")
    job.state, job.attempts, job.error = "queued", 0, None
    job.finished_at, job.channel_id = None, None
    job.next_attempt_at = now or utcnow()


# ------------------------------------------------------------------- reports


_FIELDS = ("Direction", "Job", "Inbox", "Org", "File", "Status", "Error", "Pages", "Remote", "Cause", "Caller")


def parse_userevent(userevent: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _FIELDS:
        value = userevent.get(key)
        if value is None:
            value = userevent.get(key.lower())
        out[key.lower()] = str(value or "").strip()
    return out


def handle_userevent(
    db: Session, settings: Settings, userevent: dict[str, Any], now: datetime | None = None
) -> FaxJob | None:
    """``UserEvent(VeyraFax)`` from the fax contexts (generator._fax_contexts)."""
    f = parse_userevent(userevent)
    now = now or utcnow()
    if f["direction"] == "out":
        return _finish_outbound(db, settings, f, now)
    if f["direction"] == "in":
        return _receive(db, settings, f, now)
    log.warning("Fax event without a direction: %s", f)
    return None


def _finish_outbound(
    db: Session, settings: Settings, f: dict[str, str], now: datetime
) -> FaxJob | None:
    try:
        job = db.get(FaxJob, uuid.UUID(f["job"]))
    except ValueError:
        job = None
    if job is None or job.state not in ACTIVE_STATES:
        return None
    job.remote_id = f["remote"][:64] or None
    job.channel_id = None
    if f["status"].upper() == "SUCCESS":
        job.state = "sent"
        job.pages = int(f["pages"] or 0) or job.pages
        job.error = None
        job.finished_at = now
        _notify_user(db, settings, job)
        return job
    error = f["error"] or f"The fax failed ({f['status'] or 'no status'})."
    # It connected but the transmission failed: one more try, not three.
    _retry_or_fail(db, settings, job, error, now, min(MAX_ATTEMPTS, 2))
    return job


def channel_gone(
    db: Session,
    settings: Settings,
    channel_id: str,
    *,
    cause: Any = None,
    cause_txt: str | None = None,
    now: datetime | None = None,
) -> FaxJob | None:
    """The originated channel ended without the fax context's report: the
    call did not connect (busy, no answer, rejected)."""
    job = db.scalar(
        select(FaxJob).where(
            FaxJob.channel_id == channel_id, FaxJob.state.in_(("dialling", "sending"))
        )
    )
    if job is None:
        return None
    now = now or utcnow()
    try:
        code = int(cause) if cause is not None else None
    except (TypeError, ValueError):
        code = None
    text = cause_txt or (f"cause {code}" if code is not None else "the call ended")
    retryable = code in RETRY_CAUSES
    _retry_or_fail(
        db,
        settings,
        job,
        f"The call did not connect: {text}.",
        now,
        MAX_ATTEMPTS if retryable else job.attempts,
    )
    return job


def _receive(db: Session, settings: Settings, f: dict[str, str], now: datetime) -> FaxJob | None:
    inbox = db.scalar(select(FaxInbox).where(FaxInbox.slug == f["inbox"]))
    org = db.get(Organization, inbox.organization_id) if inbox else None
    if inbox is None or org is None:
        log.warning("Fax received for an unknown inbox %r", f["inbox"])
        return None
    ok = f["status"].upper() == "SUCCESS"
    job = FaxJob(
        id=uuid.uuid4(),
        organization_id=org.id,
        inbox_id=inbox.id,
        direction="in",
        number=normalize_number(f["caller"]) or (f["caller"][:32] or "unknown"),
        remote_id=f["remote"][:64] or None,
        pages=int(f["pages"] or 0),
        state="received" if ok else "failed",
        error=None if ok else (f["error"] or f"Receiving failed ({f['status'] or 'no status'})."),
        attempts=1,
        started_at=now,
        finished_at=now,
    )
    src = Path(f["file"]) if f["file"] else None
    incoming = (settings.fax_dir / "incoming").resolve()
    if ok and src is not None:
        try:
            resolved = src.resolve()
            valid = resolved.parent == incoming and _INBOX_FILE_RE.match(resolved.name) is not None
        except OSError:
            valid = False
        if valid and resolved.is_file():
            rel = f"{org.slug}/{job.id}"
            try:
                _store(resolved, settings.fax_dir / f"{rel}.tiff")
                job.file = f"{rel}.tiff"
                to_pdf(settings.fax_dir / f"{rel}.tiff", settings.fax_dir / f"{rel}.pdf")
                job.pdf_file = f"{rel}.pdf"
            except (FaxError, OSError) as e:
                job.error = f"Received, but the PDF could not be made: {e}"
        else:
            job.error = "Received, but the engine's file was not found."
    db.add(job)
    db.flush()
    if job.pdf_file:
        _mail_inbox(db, settings, inbox, org, job)
    return job


# ------------------------------------------------------------------- email


def _sender(db: Session) -> tuple[str, str] | None:
    smtp = mail.load_smtp_settings(db)
    if not smtp.enabled:
        return None
    inst = db.scalar(select(Installation))
    return mail.sender(smtp, inst.name if inst else "Veyra")


def _enqueue(settings: Settings, message: Any) -> None:
    settings.mailqueue_dir.mkdir(parents=True, exist_ok=True)
    mail.enqueue(settings.mailqueue_dir, message.as_bytes())


def _notify_user(db: Session, settings: Settings, job: FaxJob) -> None:
    """Email the sender when a fax is delivered or given up on."""
    user = db.get(User, job.user_id) if job.user_id else None
    sender = _sender(db) if user is not None and user.email else None
    if user is None or sender is None:
        return
    from_address, from_name = sender
    if job.state == "sent":
        subject = f"Fax to {job.number} delivered ({job.pages} page{'s' if job.pages != 1 else ''})"
        text = (
            f"Your fax to {job.number} was delivered"
            + (f" to station {job.remote_id}" if job.remote_id else "")
            + f".\n\nPages: {job.pages}\nFile: {job.original_name or '-'}\n"
        )
    else:
        subject = f"Fax to {job.number} failed"
        text = (
            f"Your fax to {job.number} could not be delivered after {job.attempts} attempt"
            f"{'s' if job.attempts != 1 else ''}.\n\nReason: {job.error or '-'}\n"
            f"File: {job.original_name or '-'}\n\nYou can retry it from My Phone.\n"
        )
    try:
        msg = mail.compose(
            from_address=from_address, from_name=from_name, to=user.email, subject=subject, text=text
        )
        _enqueue(settings, msg)
    except OSError:
        log.exception("Could not queue the fax notification")


def _mail_inbox(
    db: Session, settings: Settings, inbox: FaxInbox, org: Organization, job: FaxJob
) -> None:
    """The received PDF to the inbox's recipients."""
    recipients = [r for r in (inbox.recipients or []) if r]
    sender = _sender(db) if recipients else None
    pdf = file_path(settings, job.pdf_file)
    if sender is None or pdf is None:
        return
    from_address, from_name = sender
    data = pdf.read_bytes()
    stamp = (job.finished_at or utcnow()).strftime("%Y%m%d-%H%M")
    filename = f"fax-{stamp}-{re.sub(r'[^0-9+]', '', job.number) or 'unknown'}.pdf"
    text = (
        f"A fax arrived on {inbox.name} ({org.name}).\n\n"
        f"From: {job.number}" + (f" ({job.remote_id})" if job.remote_id else "") + "\n"
        f"Pages: {job.pages}\n\nThe pages are attached as a PDF.\n"
    )
    for to in recipients:
        try:
            msg = mail.compose(
                from_address=from_address,
                from_name=from_name,
                to=to,
                subject=f"Fax from {job.number} for {inbox.name} ({job.pages} page"
                f"{'s' if job.pages != 1 else ''})",
                text=text,
                attachments=[(filename, "application/pdf", data)],
            )
            _enqueue(settings, msg)
        except OSError:
            log.exception("Could not queue the received fax")


# ------------------------------------------------------------------- retention


def remove_files(settings: Settings, job: FaxJob) -> None:
    for rel in (job.file, job.pdf_file):
        path = file_path(settings, rel)
        if path is not None:
            try:
                path.unlink()
            except OSError:
                pass
