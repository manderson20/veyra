# SPDX-License-Identifier: AGPL-3.0-or-later
"""The voicemail store helper (docs/USER_PORTAL.md §2.2): file operations
on a spool laid out like Asterisk's, and the socket protocol."""

import base64
import threading
import time

import pytest

from veyra.voicemail import client as vmclient
from veyra.voicemail import store as vmstore

TXT = """;
; Message Information file
;
[message]
origmailbox=1001
context=veyra
exten=1001
rdnis=unknown
priority=4
callerchan=PJSIP/example-1002-00000001
callerid="Pat Lee" <1002>
origdate=Sat Oct 18 09:15:02 PM UTC 2026
origtime={origtime}
category=
msg_id={msg_id}
flag={flag}
duration={duration}
"""


def _msg(folder, n, *, origtime=1760800000, duration=7, flag=""):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"msg{n:04d}.txt").write_text(
        TXT.format(
            origtime=origtime + n, msg_id=f"{origtime + n}-{n:08d}", flag=flag, duration=duration
        )
    )
    (folder / f"msg{n:04d}.wav").write_bytes(b"RIFF" + bytes([n]) * 16)


@pytest.fixture
def spool(tmp_path):
    root = tmp_path / "voicemail"
    inbox = root / "veyra" / "1001" / "INBOX"
    for n in range(3):
        _msg(inbox, n, flag="Urgent" if n == 1 else "")
    _msg(root / "veyra" / "1001" / "Old", 0)
    (root / "veyra" / "1001" / "greet.wav").write_bytes(b"RIFFname")
    return root


def test_list_read_and_validation(spool):
    st = vmstore.VoicemailStore(spool)
    out = st.list_messages(_a(folder="INBOX"))
    assert [m["number"] for m in out["messages"]] == [0, 1, 2]
    assert out["messages"][1]["urgent"] and out["messages"][0]["callerid"] == '"Pat Lee" <1002>'
    assert out["messages"][0]["duration"] == 7 and out["messages"][0]["format"] == "wav"
    assert out["counts"] == {
        "INBOX": 3,
        "Old": 1,
        "Work": 0,
        "Family": 0,
        "Friends": 0,
        "Urgent": 0,
    }
    r = st.read({"context": "veyra", "mailbox": "1001", "folder": "INBOX", "number": 2})
    assert base64.b64decode(r["data"]).startswith(b"RIFF\x02") and r["message"]["number"] == 2
    # Nothing outside the fixed shapes is touched.
    for bad in (
        {"context": "../etc", "mailbox": "1001"},
        {"context": "veyra", "mailbox": "1001/../1002"},
        {"context": "veyra", "mailbox": "1001", "folder": "Trash"},
    ):
        with pytest.raises(vmstore.StoreError) as e:
            st.list_messages(bad)
        assert e.value.code == "bad_argument"
    with pytest.raises(vmstore.StoreError) as e:
        st.read({"context": "veyra", "mailbox": "1001", "folder": "INBOX", "number": 9})
    assert e.value.code == "not_found"
    # A symlinked message is not followed.
    inbox = spool / "veyra" / "1001" / "INBOX"
    (inbox / "msg0005.txt").symlink_to("/etc/hostname")
    with pytest.raises(vmstore.StoreError):
        st.read({"context": "veyra", "mailbox": "1001", "folder": "INBOX", "number": 5})


def _a(**kw):
    return {"context": "veyra", "mailbox": "1001", **kw}


def test_move_delete_copy_renumber_and_lock(spool):
    st = vmstore.VoicemailStore(spool)
    inbox = spool / "veyra" / "1001" / "INBOX"
    old = spool / "veyra" / "1001" / "Old"
    # Move the middle message: INBOX closes the gap, Old appends.
    r = st.move(
        {"context": "veyra", "mailbox": "1001", "folder": "INBOX", "number": 1, "to": "Old"}
    )
    assert r == {"moved": True, "number": 1}
    assert sorted(p.name for p in inbox.iterdir()) == [
        "msg0000.txt",
        "msg0000.wav",
        "msg0001.txt",
        "msg0001.wav",
    ]
    assert (inbox / "msg0001.wav").read_bytes().startswith(b"RIFF\x02")  # the old msg0002
    assert (old / "msg0001.txt").read_text().count("flag=Urgent") == 1
    # The msg_id guard refuses a stale list.
    with pytest.raises(vmstore.StoreError) as e:
        st.delete(
            {
                "context": "veyra",
                "mailbox": "1001",
                "folder": "INBOX",
                "number": 0,
                "msg_id": "nope",
            }
        )
    assert e.value.code == "message_moved"
    entry = st.list_messages(_a(folder="INBOX"))["messages"][0]
    assert st.delete(
        {
            "context": "veyra",
            "mailbox": "1001",
            "folder": "INBOX",
            "number": 0,
            "msg_id": entry["msg_id"],
        }
    )
    assert sorted(p.name for p in inbox.iterdir()) == ["msg0000.txt", "msg0000.wav"]
    # Forward: a copy lands in the other box's INBOX with a note; the source stays.
    r = st.copy(
        {
            "context": "veyra",
            "mailbox": "1001",
            "folder": "INBOX",
            "number": 0,
            "to_context": "veyra",
            "to_mailbox": "1002",
            "note": "Pat Lee (1001)",
        }
    )
    assert r == {"copied": True, "number": 0}
    assert (
        "forwarded_by=Pat Lee (1001)"
        in (spool / "veyra" / "1002" / "INBOX" / "msg0000.txt").read_text()
    )
    assert (inbox / "msg0000.txt").exists()
    # Moving into a new folder creates it; a held lock makes the store wait, then fail.
    assert st.move(
        {"context": "veyra", "mailbox": "1001", "folder": "INBOX", "number": 0, "to": "Work"}
    )["moved"]
    (spool / "veyra" / "1001" / "Work" / ".lock").write_text("")
    with pytest.raises(vmstore.StoreError) as e:
        vmstore._FolderLock(spool / "veyra" / "1001" / "Work", timeout=0.2).__enter__()
    assert e.value.code == "busy"


def test_greetings(spool):
    st = vmstore.VoicemailStore(spool)
    g = st.greetings({"context": "veyra", "mailbox": "1001"})["greetings"]
    assert g["greet"]["format"] == "wav" and g["unavail"] is None
    st.greeting_put(
        {
            "context": "veyra",
            "mailbox": "1001",
            "kind": "unavail",
            "format": "wav",
            "data": base64.b64encode(b"RIFFunavail").decode(),
        }
    )
    assert (spool / "veyra" / "1001" / "unavail.wav").read_bytes() == b"RIFFunavail"
    # Replacing removes other formats of the same greeting.
    (spool / "veyra" / "1001" / "unavail.gsm").write_bytes(b"old")
    st.greeting_put(
        {
            "context": "veyra",
            "mailbox": "1001",
            "kind": "unavail",
            "format": "wav",
            "data": base64.b64encode(b"RIFFnew").decode(),
        }
    )
    assert not (spool / "veyra" / "1001" / "unavail.gsm").exists()
    r = st.greeting_get({"context": "veyra", "mailbox": "1001", "kind": "unavail"})
    assert base64.b64decode(r["data"]) == b"RIFFnew"
    assert st.greeting_delete({"context": "veyra", "mailbox": "1001", "kind": "unavail"})["deleted"]
    assert not st.greeting_delete({"context": "veyra", "mailbox": "1001", "kind": "unavail"})[
        "deleted"
    ]
    with pytest.raises(vmstore.StoreError):
        st.greeting_put({"context": "veyra", "mailbox": "1001", "kind": "hello", "data": "QUJD"})
    # A box that does not exist yet is created for its first greeting.
    st.greeting_put(
        {
            "context": "veyra",
            "mailbox": "1003",
            "kind": "temp",
            "data": base64.b64encode(b"RIFFt").decode(),
        }
    )
    assert (spool / "veyra" / "1003" / "temp.wav").exists()


def test_socket_protocol_and_client(spool, tmp_path):
    st = vmstore.VoicemailStore(spool)
    sock = tmp_path / "vmstore.sock"
    t = threading.Thread(target=st.serve, args=(sock,), kwargs={"once": False}, daemon=True)
    t.start()
    for _ in range(50):
        if sock.exists():
            break
        time.sleep(0.05)
    c = vmclient.StoreClient(sock, timeout=5)
    assert c.ping()["readable"]
    out = c.list("veyra", "1001")
    assert out["counts"]["INBOX"] == 3
    fmt, data = c.read("veyra", "1001", "INBOX", 0)
    assert fmt == "wav" and data.startswith(b"RIFF")
    assert c.move("veyra", "1001", "INBOX", 0, "Old")["moved"]
    assert c.delete("veyra", "1001", "Old", 1)["deleted"]
    assert c.copy("veyra", "1001", "INBOX", 0, "veyra", "1002", "x")["copied"]
    c.greeting_put("veyra", "1001", "busy", b"RIFFbusy")
    assert c.greetings("veyra", "1001")["busy"]["size"] == 8
    assert c.greeting_get("veyra", "1001", "busy") == ("wav", b"RIFFbusy")
    assert c.greeting_delete("veyra", "1001", "busy")
    with pytest.raises(vmclient.StoreClientError) as e:
        c.call("explode")
    assert e.value.code == "unknown_verb"
    with pytest.raises(vmclient.StoreClientError) as e:
        c.list("veyra", "1001", "Trash")
    assert e.value.code == "bad_argument"
    # No helper: a distinct error the API turns into 503.
    with pytest.raises(vmclient.StoreUnavailable):
        vmclient.StoreClient(tmp_path / "missing.sock").ping()
    # The raw protocol rejects garbage without dying.
    assert b'"ok":false' in st.handle(b"not json")
