# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
from pydantic import ValidationError

from veyra.telephony.adapter import GeneratedFile
from veyra.telephony.asterisk import generator
from veyra.telephony.settings import SipSettings


def _snapshot(**overrides):
    snap = {
        "installation": {"name": "Test District"},
        "sip": SipSettings().model_dump(mode="json"),
        "organizations": [{"slug": "example", "name": "Example", "timezone": "UTC"}],
        "extensions": [],
    }
    snap.update(overrides)
    return snap


def test_generation_is_deterministic_and_complete():
    a = generator.generate(_snapshot())
    b = generator.generate(_snapshot())
    assert [(f.path, f.content) for f in a] == [(f.path, f.content) for f in b]
    assert [f.path for f in a] == generator.MANAGED_FILES
    by = {f.path: f for f in a}
    assert "[veyra-transport-udp]" in by["pjsip.transports.conf"].content
    assert "bind=0.0.0.0:5060" in by["pjsip.transports.conf"].content
    assert "[veyra-transport-tcp]" in by["pjsip.transports.conf"].content
    assert "[veyra-transport-tls]" not in by["pjsip.transports.conf"].content
    assert "allow=ulaw,alaw,g722" in by["pjsip.endpoints.conf"].content
    assert not by["pjsip.endpoints.conf"].sensitive  # no secrets without extensions
    assert "[veyra-internal]" in by["extensions.conf"].content
    assert "exten => *43,1," in by["extensions.conf"].content
    assert "VEYRA_INSTALLATION=Test District" in by["extensions.conf"].content
    assert "rtpstart=10000" in by["rtp.conf"].content
    assert all(f.content.startswith("; Managed by Veyra") for f in a)
    assert generator.validate(a) == []


def test_nat_and_tls_settings_are_rendered():
    sip = SipSettings(
        external_signaling_address="203.0.113.5",
        external_media_address="203.0.113.5",
        local_nets=["10.0.0.0/8", "172.16.2.0/24"],
        tls_enabled=True,
        tcp_enabled=False,
    )
    assert sip.problems() == []
    files = {f.path: f for f in generator.generate(_snapshot(sip=sip.model_dump(mode="json")))}
    t = files["pjsip.transports.conf"].content
    assert "external_signaling_address=203.0.113.5" in t
    assert "local_net=10.0.0.0/8" in t and "local_net=172.16.2.0/24" in t
    assert "[veyra-transport-tls]" in t and "bind=0.0.0.0:5061" in t
    assert "[veyra-transport-tcp]" not in t


def test_extensions_render_endpoints_and_dialplan_and_mark_sensitive():
    ext = {
        "endpoint_name": "example-1001",
        "number": "1001",
        "display_name": "Front Office",
        "organization": "example",
        "caller_id_name": None,
        "caller_id_number": None,
        "secret": "s3cret-value",
    }
    files = {f.path: f for f in generator.generate(_snapshot(extensions=[ext]))}
    ep = files["pjsip.endpoints.conf"]
    assert ep.sensitive
    assert "[example-1001](veyra-endpoint)" in ep.content
    assert "password=s3cret-value" in ep.content
    assert 'callerid="Front Office" <1001>' in ep.content
    assert "exten => 1001,1,NoOp(Veyra extension 1001)" in files["extensions.conf"].content
    assert "Dial(PJSIP/example-1001,30)" in files["extensions.conf"].content


def test_feature_codes_are_not_shadowed_by_the_catch_all():
    """Asterisk matches patterns in the current context before it searches
    includes, so the invalid-number catch-all must not live in veyra-internal
    itself or *43/*60 would never be reached (found on dev1, 2026-10-13)."""
    ext = {"endpoint_name": "example-1001", "number": "1001", "display_name": "A", "secret": "x"}
    files = {f.path: f for f in generator.generate(_snapshot(extensions=[ext]))}
    dialplan = files["extensions.conf"].content
    sections = {}
    current = None
    for line in dialplan.splitlines():
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections[current] = []
        elif current:
            sections[current].append(line.strip())
    internal = sections[generator.CONTEXT_INTERNAL]
    assert not any(ln.startswith("exten => _") for ln in internal)
    includes = [ln for ln in internal if ln.startswith("include =>")]
    assert includes == [
        f"include => {generator.CONTEXT_FEATURES}",
        f"include => {generator.CONTEXT_OUTBOUND}",
        f"include => {generator.CONTEXT_INVALID}",
    ]
    assert any(ln.startswith("exten => _[0-9*#+].") for ln in sections[generator.CONTEXT_INVALID])
    assert any(ln.startswith("exten => *43") for ln in sections[generator.CONTEXT_FEATURES])


@pytest.mark.parametrize(
    "bad",
    [
        {"endpoint_name": "bad name]", "number": "1001", "secret": "x"},
        {"endpoint_name": "ok", "number": "10;01", "secret": "x"},
        {"endpoint_name": "ok", "number": "1001", "secret": None},
        {"endpoint_name": "ok", "number": "1001", "secret": "a\nb"},
    ],
)
def test_generation_rejects_unsafe_values(bad):
    bad.setdefault("display_name", "X")
    with pytest.raises(generator.GenerationError):
        generator.generate(_snapshot(extensions=[bad]))


def test_duplicate_endpoint_names_are_rejected():
    e = {"endpoint_name": "dup", "number": "1001", "display_name": "A", "secret": "x"}
    with pytest.raises(generator.GenerationError, match="duplicate"):
        generator.generate(_snapshot(extensions=[e, {**e, "number": "1002"}]))


def test_static_validation_catches_malformed_files():
    assert generator.validate([GeneratedFile("extensions.conf", "key=value\n")]) == [
        "extensions.conf:1: key outside a section"
    ]
    assert generator.validate([GeneratedFile("other.conf", "[a]\n")]) == [
        "other.conf: not a file Veyra manages"
    ]
    assert "malformed section" in generator.validate([GeneratedFile("rtp.conf", "[a b]\n")])[0]
    assert (
        "control character" in generator.validate([GeneratedFile("rtp.conf", "[a]\nx=\x01\n")])[0]
    )


def test_reload_scopes_are_minimal_and_ordered():
    assert generator.reload_scopes(["extensions.conf"]) == ["pbx_config.so"]
    assert generator.reload_scopes(["pjsip.endpoints.conf", "pjsip.transports.conf"]) == [
        "res_pjsip.so"
    ]
    assert generator.reload_scopes(["extensions.conf", "rtp.conf", "pjsip.endpoints.conf"]) == [
        "res_rtp_asterisk.so",
        "res_pjsip.so",
        "pbx_config.so",
    ]
    assert generator.reload_scopes(["unknown"]) == []


def test_sip_settings_validation():
    with pytest.raises(ValidationError):
        SipSettings(codecs=["mp3"])
    with pytest.raises(ValidationError):
        SipSettings(bind_address="not-an-ip")
    with pytest.raises(ValidationError):
        SipSettings(local_nets=["10.0.0.0/99"])
    with pytest.raises(ValidationError):
        SipSettings(external_signaling_address="bad host!")
    s = SipSettings(codecs=["ULAW", "ulaw", "opus"], local_nets=["10.1.2.3/8", " "])
    assert s.codecs == ["ulaw", "opus"] and s.local_nets == ["10.0.0.0/8"]
    assert SipSettings(rtp_start=5000, rtp_end=6000).problems() == [
        "SIP port 5060 lies inside the RTP range."
    ]
    assert "span at least 100" in SipSettings(rtp_start=10000, rtp_end=10050).problems()[0]
    assert "both external" in SipSettings(external_signaling_address="1.2.3.4").problems()[0]
    assert (
        "local networks"
        in SipSettings(
            external_signaling_address="pbx.example.org", external_media_address="pbx.example.org"
        ).problems()[0]
    )
