from __future__ import annotations

import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from network_change_delivery.oxidized_controller import CollectionReady
from network_change_delivery.oxidized_reconciler import _inspect
from network_change_delivery.oxidized_service import (
    OxidizedServiceError,
    docker_run_arguments,
    invalidate_readiness,
    publish_readiness,
    render_oxidized_config,
    validate_history_reservation,
)

IMAGE = "sha256:" + "a" * 64


def test_persistent_config_freezes_no_poll_git_contract() -> None:
    config = render_oxidized_config()
    for contract in (
        "interval: 0",
        "threads: 1",
        "retries: 0",
        "next_adds_job: true",
        "default: jsonfile",
        "default: git",
        "single_repo: true",
        "NCDP Oxidized",
        "oxidized@ncdp.local",
        "/var/lib/ncdp/config-history.git",
        "type_as_directory: false",
    ):
        assert contract in config
    assert "clean_obsolete_nodes" not in config


def test_docker_contract_is_nonroot_private_and_minimal(tmp_path: Path) -> None:
    args = docker_run_arguments(
        image_id=IMAGE,
        config_path=tmp_path / "config",
        source_path=tmp_path / "router.json",
        history_path=tmp_path / "history.git",
        uid=501,
        gid=20,
    )
    rendered = " ".join(args)
    assert args[0] == "/usr/local/bin/docker"
    assert "--user 501:20" in rendered
    assert "--read-only" in args
    assert "--cap-drop ALL" in rendered
    assert "no-new-privileges" in rendered
    assert "127.0.0.1:8888:8888" in rendered
    assert "--restart no" in rendered
    assert "docker.sock" not in rendered
    assert "AuditStore" not in rendered
    assert "operator" not in rendered
    assert "OPENBAO" not in rendered
    assert "NETBOX" not in rendered


def test_readiness_is_private_bounded_and_invalidatable(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    path = runtime / "collection-ready.json"
    now = datetime.now(UTC)
    marker = publish_readiness(path, "a" * 64, now=now)
    assert marker == CollectionReady.model_validate_json(path.read_bytes())
    assert marker.expires_at == now + timedelta(minutes=15)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    invalidate_readiness(path)
    assert not path.exists()


@pytest.mark.skipif(
    not Path("/usr/bin/git").is_file(), reason="fixed host Git CLI unavailable"
)
def test_history_reservation_rejects_public_directory(tmp_path: Path) -> None:
    history = tmp_path / "history.git"
    subprocess.run(
        ["/usr/bin/git", "init", "--bare", str(history)],
        check=True,
        capture_output=True,
    )
    history.chmod(0o700)
    validate_history_reservation(history)
    history.chmod(0o750)
    with pytest.raises(OxidizedServiceError, match="reservation rejected"):
        validate_history_reservation(history)


def test_installer_freezes_launchd_and_external_runtime_contract() -> None:
    root = Path(__file__).parents[1]
    script = (root / "scripts/oxidized/install_service.sh").read_text()
    assert "com.ncdp.oxidized" in script
    assert "<key>RunAtLoad</key><true/>" in script
    assert "<key>StartInterval</key><integer>300</integer>" in script
    assert "/Users/netdevops/.local/lib/ncdp/oxidized-service" in script
    assert "uv run" not in script
    assert "--editable" not in script
    assert "oxidized-service.candidate" not in script
    assert "BAO_TOKEN" not in script
    assert "OPENBAO_TOKEN" not in script
    assert "docker.sock" not in script


def test_missing_docker_inspection_is_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "network_change_delivery.oxidized_reconciler._docker",
        lambda *_args, **_kwargs: "[]",
    )
    assert _inspect() is None
