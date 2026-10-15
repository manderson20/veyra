#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A minimal SIP phone for testing Veyra without a handset.

It registers one extension over UDP (digest authentication), answers the
engine's OPTIONS pings so the contact qualifies, rings on INVITE and answers
after a delay with a PCMU/PCMA SDP, and acknowledges BYE and CANCEL. With
``--tone`` it sends a 440 Hz tone as PCMU while a call is up (for testing
call recording); otherwise no media. Standard library only; run it on the
server itself:

    python3 -I tools/fakephone.py --user <endpoint-name> --password <sip-secret>

The endpoint name and SIP secret are on the extension page (or in
``sudo asterisk -rx "pjsip show auth <endpoint>"``). See docs/DEVELOPMENT.md §3b.
"""

import argparse
import hashlib
import math
import struct
import threading
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
ap.add_argument("--local-ip", default="127.0.0.1", help="address to bind and advertise")
ap.add_argument("--answer-after", type=float, default=3.0)
ap.add_argument("--expires", type=int, default=120)
ap.add_argument(
    "--no-register", action="store_true", help="act as a carrier: never REGISTER"
)
ap.add_argument(
    "--call", help="place one call to this number right away (as a carrier would)"
)
ap.add_argument(
    "--from-user", default=None, help="From user for --call (default: --user)"
)
ap.add_argument(
    "--header",
    action="append",
    default=[],
    help="extra header for --call, 'Name: value'",
)
ap.add_argument(
    "--hangup-after", type=float, default=0, help="end the placed call after N seconds"
)
ap.add_argument(
    "--tone", action="store_true", help="send a 440 Hz tone while a call is up"
)
args = ap.parse_args()

LOCAL_IP = args.local_ip
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


def sdp():
    return (
        f"v=0\r\no=- 1 1 IN IP4 {LOCAL_IP}\r\ns=-\r\nc=IN IP4 {LOCAL_IP}\r\nt=0 0\r\n"
        f"m=audio {rtp_port} RTP/AVP 0 8 101\r\na=rtpmap:0 PCMU/8000\r\na=rtpmap:8 PCMA/8000\r\n"
        f"a=rtpmap:101 telephone-event/8000\r\na=sendrecv\r\n"
    )


call = {}  # the one outgoing call: Call-ID, tags, CSeq, remote target


def invite(number, auth=None):
    """Send an INVITE for ``number`` to the server (a phone or carrier placing a call).
    With ``auth`` (a digest answer to a 401/407) the same dialog is retried."""
    global cseq
    cseq += 1
    user = args.from_user or args.user
    if auth is None:
        call["call_id"] = str(uuid.uuid4())
        call["from_tag"] = uuid.uuid4().hex[:10]
    call.update(
        {
            "to": f"<sip:{number}@{args.server}>",
            "cseq": cseq,
            "number": number,
            "state": "calling",
            "started": None,
        }
    )
    body = sdp()
    msg = (
        f"INVITE sip:{number}@{args.server}:{args.port} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {LOCAL_IP}:{args.local_port};branch=z9hG4bK{uuid.uuid4().hex[:12]};rport\r\n"
        f"Max-Forwards: 70\r\n"
        f'From: "{user}" <sip:{user}@{LOCAL_IP}>;tag={call["from_tag"]}\r\n'
        f"To: {call['to']}\r\n"
        f"Call-ID: {call['call_id']}\r\nCSeq: {cseq} INVITE\r\n"
        f"Contact: {contact}\r\n"
        f"User-Agent: Veyra fake carrier\r\n"
    )
    for h in args.header:
        msg += h.strip() + "\r\n"
    if auth:
        msg += f"Authorization: {auth}\r\n"
    msg += f"Content-Type: application/sdp\r\nContent-Length: {len(body)}\r\n\r\n{body}"
    send(msg)
    log(f"CALLING {number} (INVITE sent{' with credentials' if auth else ''})")


def ack_or_bye(method, to_header):
    global cseq
    if method == "BYE":
        cseq += 1
        num = cseq
    else:
        num = call["cseq"]
    user = args.from_user or args.user
    msg = (
        f"{method} sip:{call['number']}@{args.server}:{args.port} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {LOCAL_IP}:{args.local_port};branch=z9hG4bK{uuid.uuid4().hex[:12]};rport\r\n"
        f"Max-Forwards: 70\r\n"
        f'From: "{user}" <sip:{user}@{LOCAL_IP}>;tag={call["from_tag"]}\r\n'
        f"To: {to_header}\r\n"
        f"Call-ID: {call['call_id']}\r\nCSeq: {num} {method}\r\n"
        f"Content-Length: 0\r\n\r\n"
    )
    send(msg)


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


def _ulaw(sample):
    """16-bit linear PCM to G.711 mu-law."""
    sign = 0x80 if sample < 0 else 0
    sample = min(abs(sample), 32635) + 132
    exponent = 7
    for exp, limit in enumerate((256, 512, 1024, 2048, 4096, 8192, 16384, 32768)):
        if sample < limit:
            exponent = exp
            break
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


TONE = bytes(_ulaw(int(8000 * math.sin(2 * math.pi * 440 * n / 8000))) for n in range(8000))
media = {"target": None, "on": False}


def remote_media(sdp_text):
    ip = re.search(r"^c=IN IP4 (\S+)", sdp_text, re.M)
    port = re.search(r"^m=audio (\d+)", sdp_text, re.M)
    return (ip.group(1), int(port.group(1))) if ip and port else None


def rtp_sender():
    rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rtp.bind((LOCAL_IP, rtp_port))
    seq, ts, ssrc, offset = random.randrange(65536), random.randrange(2**32), random.randrange(2**32), 0
    while True:
        if media["on"] and media["target"]:
            payload = (TONE + TONE)[offset : offset + 160]
            offset = (offset + 160) % len(TONE)
            rtp.sendto(struct.pack("!BBHII", 0x80, 0, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc) + payload, media["target"])
            seq, ts = seq + 1, ts + 160
        time.sleep(0.02)


to_tag = uuid.uuid4().hex[:10]
last_peer = SERVER
pending_invite = None
answer_at = None
rtp_port = random.randrange(20000, 30000, 2)
if args.tone:
    threading.Thread(target=rtp_sender, daemon=True).start()
if not args.no_register:
    register()
next_register = time.time() + args.expires * 0.8
registered = False
if args.call:
    invite(args.call)

while True:
    now = time.time()
    if pending_invite and answer_at and now >= answer_at:
        reply(
            pending_invite,
            200,
            "OK",
            f"Contact: {contact}\r\nContent-Type: application/sdp\r\n",
            sdp(),
        )
        log("ANSWERED call (200 OK sent)")
        pending_invite, answer_at = None, None
    if now >= next_register and not args.no_register:
        register()
        next_register = now + args.expires * 0.8
    if (
        call.get("state") == "up"
        and args.hangup_after
        and now - call["started"] >= args.hangup_after
    ):
        ack_or_bye("BYE", call["remote_to"])
        call["state"] = "ended"
        media["on"] = False
        log("BYE sent: placed call ENDED")
    try:
        data, last_peer = sock.recvfrom(65535)
    except TimeoutError:
        continue
    msg = data.decode(errors="replace")
    first = msg.split("\r\n", 1)[0]
    if first.startswith("SIP/2.0"):
        code = int(first.split()[1])
        method = hdr(msg, "CSeq").split()[-1]
        if method == "INVITE" and call:
            if code < 200:
                if code == 180 or code == 183:
                    log(f"placed call: remote is RINGING ({code})")
            elif code < 300:
                call["remote_to"] = hdr(msg, "To")
                ack_or_bye("ACK", call["remote_to"])
                if call.get("state") != "up":
                    call["state"] = "up"
                    call["started"] = now
                    media["target"], media["on"] = remote_media(msg), args.tone
                    log("placed call ANSWERED (200 OK, ACK sent)")
            elif code in (401, 407) and not call.get("authed"):
                call["remote_to"] = hdr(msg, "To")
                ack_or_bye("ACK", call["remote_to"])
                call["authed"] = True
                challenge = hdr(msg, "WWW-Authenticate") or hdr(
                    msg, "Proxy-Authenticate"
                )
                invite(
                    call["number"],
                    digest(
                        challenge,
                        "INVITE",
                        f"sip:{call['number']}@{args.server}:{args.port}",
                    ),
                )
            else:
                call["remote_to"] = hdr(msg, "To")
                ack_or_bye("ACK", call["remote_to"])
                call["state"] = "failed"
                log(f"placed call FAILED: {first}")
            continue
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
        media["target"] = remote_media(msg)
    elif method == "ACK":
        log("ACK received: call is UP")
        media["on"] = args.tone
    elif method == "BYE":
        reply(msg, 200, "OK")
        log("BYE received: call ENDED")
        media["on"] = False
        pending_invite = None
        if call:
            call["state"] = "ended"
    elif method == "CANCEL":
        reply(msg, 200, "OK")
        if pending_invite:
            reply(pending_invite, 487, "Request Terminated")
        pending_invite = None
        log("CANCEL received: ringing stopped")
    else:
        reply(msg, 200, "OK")
