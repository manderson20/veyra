# SPDX-License-Identifier: AGPL-3.0-or-later
"""Revision service and deployer with a fake engine and a temporary directory."""

import os
import stat

from conftest import ADMIN_EMAIL, complete_setup
from fake_adapter import FakeAdapter

from veyra.configmgmt import service
from veyra.configmgmt.revisions import RevisionState
from veyra.core.db import session_scope
from veyra.core.security.crypto import load_installation_key
from veyra.telephony.settings import SipSettings, save_sip_settings


def _key(client):
    return load_installation_key(client.app.state.settings)


def _deployer(adapter, tmp_path, client):
    d = tmp_path / "asterisk-veyra"
    d.mkdir()
    return service.Deployer(adapter, d, _key(client)), d


def test_generate_deploy_supersede_and_rollback(client, tmp_path):
    complete_setup(client)
    adapter = FakeAdapter()
    deployer, cfg = _deployer(adapter, tmp_path, client)

    with session_scope() as db:
        g1 = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        assert g1.revision.state == RevisionState.VALIDATED
        assert g1.revision.summary == "Initial configuration"
        assert set(g1.diff) == set(adapter.managed_files())
        assert not g1.unchanged
        service.request_deploy(db, g1.revision)
        r1 = g1.revision.id

    with session_scope() as db:
        rev = deployer.run_once(db)
        assert rev is not None and rev.id == r1 and rev.state == RevisionState.DEPLOYED
        assert rev.deployed_at is not None
    for name in adapter.managed_files():
        p = cfg / name
        assert p.exists()
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o640
    assert (cfg / "extensions.conf").read_text().startswith("; Managed by Veyra")
    assert adapter.reloads == [
        "res_rtp_asterisk.so",
        "res_pjsip.so",
        "pbx_config.so",
        "app_voicemail.so",
        "app_queue.so",
        "res_pjsip_notify.so",
        "res_musiconhold.so",
        "app_confbridge.so",
        "res_parking.so",
    ]
    assert not list(cfg.glob(".*tmp*"))

    # No change -> a revision that says so and deploys without reloading anything
    with session_scope() as db:
        g2 = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        assert g2.unchanged and g2.diff == {}
        assert g2.revision.summary == "No change from the deployed configuration"

    # A settings change -> only the affected files and reloads
    with session_scope() as db:
        save_sip_settings(db, SipSettings(rtp_start=20000, rtp_end=30000))
        g3 = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        assert set(g3.diff) == {"rtp.conf"}
        assert g3.revision.parent_id == r1
        service.request_deploy(db, g3.revision)
        r3 = g3.revision.id
    adapter.reloads.clear()
    with session_scope() as db:
        deployer.run_once(db)
        assert db.get(type(g3.revision), r3).state == RevisionState.DEPLOYED
        assert db.get(type(g3.revision), r1).state == RevisionState.SUPERSEDED
    assert adapter.reloads == ["res_rtp_asterisk.so"]
    assert "rtpstart=20000" in (cfg / "rtp.conf").read_text()

    # Roll back by deploying the superseded revision
    with session_scope() as db:
        old = db.get(type(g3.revision), r1)
        service.request_deploy(db, old)
    with session_scope() as db:
        deployer.run_once(db)
        assert db.get(type(g3.revision), r1).state == RevisionState.DEPLOYED
        assert db.get(type(g3.revision), r3).state == RevisionState.ROLLED_BACK
        assert service.current_deployed(db, "asterisk").id == r1
    assert "rtpstart=10000" in (cfg / "rtp.conf").read_text()


def test_failed_deployment_restores_previous_files(client, tmp_path):
    complete_setup(client)
    adapter = FakeAdapter()
    deployer, cfg = _deployer(adapter, tmp_path, client)
    with session_scope() as db:
        g1 = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        service.request_deploy(db, g1.revision)
        r1 = g1.revision.id
    with session_scope() as db:
        deployer.run_once(db)
    before = (cfg / "rtp.conf").read_text()

    adapter.fail_verify = ["res_rtp_asterisk.so: status is 'Not Running', expected 'Running'"]
    with session_scope() as db:
        save_sip_settings(db, SipSettings(rtp_start=30000, rtp_end=40000))
        g2 = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        service.request_deploy(db, g2.revision)
        r2 = g2.revision.id
    with session_scope() as db:
        deployer.run_once(db)
        bad = db.get(type(g2.revision), r2)
        assert bad.state == RevisionState.FAILED
        assert "Not Running" in bad.validation_errors[0]
        assert any("restored" in line for line in bad.validation_errors)
        assert db.get(type(g2.revision), r1).state == RevisionState.DEPLOYED
    assert (cfg / "rtp.conf").read_text() == before
    # a failed revision can never be queued again
    with session_scope() as db:
        import pytest

        from veyra.configmgmt.revisions import InvalidTransition

        with pytest.raises(InvalidTransition):
            service.request_deploy(db, db.get(type(g2.revision), r2))


def test_reload_failure_and_missing_directory(client, tmp_path):
    complete_setup(client)
    adapter = FakeAdapter()
    deployer = service.Deployer(adapter, tmp_path / "missing", _key(client))
    with session_scope() as db:
        g = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        service.request_deploy(db, g.revision)
        rid = g.revision.id
    with session_scope() as db:
        deployer.run_once(db)
        rev = db.get(type(g.revision), rid)
        assert rev.state == RevisionState.FAILED and "does not exist" in rev.validation_errors[0]

    adapter.fail_reload = "pbx_config.so"
    deployer, cfg = _deployer(adapter, tmp_path, client)
    with session_scope() as db:
        g = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        service.request_deploy(db, g.revision)
        rid = g.revision.id
    with session_scope() as db:
        deployer.run_once(db)
        rev = db.get(type(g.revision), rid)
        assert rev.state == RevisionState.FAILED and "pbx_config.so" in rev.validation_errors[0]
    assert not (cfg / "extensions.conf").exists()  # restored to "nothing deployed"


def test_generation_problems_make_a_failed_revision(client):
    complete_setup(client)
    adapter = FakeAdapter()
    with session_scope() as db:
        save_sip_settings(db, SipSettings(rtp_start=5000, rtp_end=6000))
        g = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        assert g.revision.state == RevisionState.FAILED
        assert "inside the RTP range" in g.revision.validation_errors[0]
        assert g.revision.artifacts == {"files": []}


def test_only_one_deployment_at_a_time(client, tmp_path):
    complete_setup(client)
    adapter = FakeAdapter()
    with session_scope() as db:
        a = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        b = service.create_revision(db, adapter, created_by=ADMIN_EMAIL, key=_key(client))
        service.request_deploy(db, a.revision)
        import pytest

        with pytest.raises(RuntimeError, match="already in progress"):
            service.request_deploy(db, b.revision)
