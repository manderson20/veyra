#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A minimal SIP phone for testing Veyra without a handset.

It registers one extension over UDP (digest authentication), answers the
engine's OPTIONS pings so the contact qualifies, rings on INVITE and answers
after a delay with a PCMU/PCMA SDP, and acknowledges BYE and CANCEL. It sends
no media. Standard library only; run it on the server itself:

    python3 -I tools/fakephone.py --user <endpoint-name> --password <sip-secret>

The endpoint name and SIP secret are on the extension page (or in
``sudo asterisk -rx "pjsip show auth <endpoint>"``). See docs/DEVELOPMENT.md §3b.
"""

import argparse
import hashlib
import random
import re
import socket
import time
import uuid

ap = argparse.ArgumentParser()
ap.add_argument("--server", default="127.0.0.1")
ap.add_argument("--port", type=int, default=5060)
ap.add_argument("--user", required=True)
ap.add_argument("--password", required=True)
ap.add_argument("--local-port", type=int, default=5080)
ap.add_argument("--answer-after", type=float, default=3.0)
ap.add_argument("--expires", type=int, default=120)
args = ap.parse_args()

LOCAL_IP = "127.0.0.1"
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((LOCAL_IP, args.local_port))
sock.settimeout(0.5)
SERVER = (args.server, args.port)
contact = f"<sip:{args.user}@{LOCAL_IP}:{args.local_port}>"
aor = f"sip:{args.user}@{args.server}"
cseq = 1
reg_call_id = str(uuid.uuid4())
from_tag = uuid.uuid4().hex[:10]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def send(data):
    sock.sendto(data.encode(), SERVER)


def hdr(msg, name):
    m = re.search(rf"^{name}:\s*(.*?)\r?$", msg, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def digest(challenge, method, uri):
    p = dict(re.findall(r'(\w+)="?([^",]+)"?', challenge))
    realm, nonce = p.get("realm", "asterisk"), p["nonce"]
    ha1 = hashlib.md5(f"{args.user}:{realm}:{args.password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    resp = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    out = (
        f'Digest username="{args.user}", realm="{realm}", nonce="{nonce}", '
        f'uri="{uri}", response="{resp}", algorithm=MD5'
    )
    if "opaque" in p:
        out += f', opaque="{p["opaque"]}"'
    return out


def register(auth=None):
    global cseq
    cseq += 1
    msg = (
        f"REGISTER sip:{args.server} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {LOCAL_IP}:{args.local_port};branch=z9hG4bK{uuid.uuid4().hex[:12]};rport\r\n"
        f"Max-Forwards: 70\r\n"
        f"From: <{aor}>;tag={from_tag}\r\nTo: <{aor}>\r\n"
        f"Call-ID: {reg_call_id}\r\nCSeq: {cseq} REGISTER\r\n"
        f"Contact: {contact}\r\nExpires: {args.expires}\r\n"
        f"User-Agent: Veyra fake phone\r\n"
    )
    if auth:
        msg += f"Authorization: {auth}\r\n"
    msg += "Content-Length: 0\r\n\r\n"
    send(msg)


def reply(req, code, reason, extra="", body=""):
    lines = []
    for name in ("Via", "From", "To", "Call-ID", "CSeq", "Record-Route"):
        for m in re.finditer(rf"^{name}:.*?\r?$", req, re.MULTILINE):
            val = m.group(0).rstrip("\r")
            if name == "To" and ";tag=" not in val and code != 100:
                val += f";tag={to_tag}"
            lines.append(val)
    msg = f"SIP/2.0 {code} {reason}\r\n" + "\r\n".join(lines) + "\r\n" + extra
    msg += f"Content-Length: {len(body)}\r\n\r\n{body}"
    sock.sendto(msg.encode(), last_peer)


to_tag = uuid.uuid4().hex[:10]
last_peer = SERVER
pending_invite = None
answer_at = None
rtp_port = random.randrange(20000, 30000, 2)
register()
next_register = time.time() + args.expires * 0.8
registered = False

while True:
    now = time.time()
    if pending_invite and answer_at and now >= answer_at:
        sdp = (
            f"v=0\r\no=- 1 1 IN IP4 {LOCAL_IP}\r\ns=-\r\nc=IN IP4 {LOCAL_IP}\r\nt=0 0\r\n"
            f"m=audio {rtp_port} RTP/AVP 0 8 101\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:8 PCMA/8000\r\n"
            f"a=rtpmap:101 telephone-event/8000\r\na=sendrecv\r\n"
        )
        reply(
            pending_invite,
            200,
            "OK",
            f"Contact: {contact}\r\nContent-Type: application/sdp\r\n",
            sdp,
        )
        log("ANSWERED call (200 OK sent)")
        pending_invite, answer_at = None, None
    if now >= next_register:
        register()
        next_register = now + args.expires * 0.8
    try:
        data, last_peer = sock.recvfrom(65535)
    except TimeoutError:
        continue
    msg = data.decode(errors="replace")
    first = msg.split("\r\n", 1)[0]
    if first.startswith("SIP/2.0"):
        code = int(first.split()[1])
        method = hdr(msg, "CSeq").split()[-1]
        if method == "REGISTER":
            if code == 401:
                register(
                    digest(
                        hdr(msg, "WWW-Authenticate"), "REGISTER", f"sip:{args.server}"
                    )
                )
            elif code == 200:
                if not registered:
                    log(
                        f"REGISTERED as {args.user} (expires {hdr(msg, 'Expires') or 'per contact'})"
                    )
                registered = True
            else:
                log(f"REGISTER -> {first}")
        continue
    method = first.split()[0]
    if method == "OPTIONS":
        reply(msg, 200, "OK", "Allow: INVITE, ACK, CANCEL, OPTIONS, BYE\r\n")
    elif method == "INVITE":
        log(
            f"RINGING: INVITE from {hdr(msg, 'From')} (will answer in {args.answer_after}s)"
        )
        reply(msg, 100, "Trying")
        reply(msg, 180, "Ringing", f"Contact: {contact}\r\n")
        pending_invite, answer_at = msg, now + args.answer_after
    elif method == "ACK":
        log("ACK received: call is UP")
    elif method == "BYE":
        reply(msg, 200, "OK")
        log("BYE received: call ENDED")
        pending_invite = None
    elif method == "CANCEL":
        reply(msg, 200, "OK")
        if pending_invite:
            reply(pending_invite, 487, "Request Terminated")
        pending_invite = None
        log("CANCEL received: ringing stopped")
    else:
        reply(msg, 200, "OK")
