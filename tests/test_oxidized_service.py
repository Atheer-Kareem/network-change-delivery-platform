from __future__ import annotations

import os
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from network_change_delivery.oxidized_controller import (
    CollectionReady,
    read_collection_ready,
)
from network_change_delivery.oxidized_reconciler import _inspect
from network_change_delivery.oxidized_service import (
    OxidizedPublicationAmbiguousError,
    OxidizedServiceError,
    docker_run_arguments,
    invalidate_readiness,
    publish_readiness,
    readiness_ambiguity_path,
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
    assert "/run/ncdp/home/.config/oxidized/config,readonly" in rendered
    assert "--config-file" not in rendered
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


def test_readiness_failure_before_replace_leaves_guard_and_rejects_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (tmp_path / "control").mkdir(mode=0o700)
    path = runtime / "collection-ready.json"
    original_replace = Path.replace

    def fail_readiness_replace(source: Path, target: Path) -> Path:
        if target == path:
            raise OSError("injected pre-commit failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_readiness_replace)
    with pytest.raises(OxidizedServiceError):
        publish_readiness(path, "a" * 64)
    assert readiness_ambiguity_path(path).is_file()
    with pytest.raises(ValueError, match="readiness rejected"):
        read_collection_ready(path, "a" * 64)


def test_post_replace_fsync_failure_is_guarded_until_successful_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (tmp_path / "control").mkdir(mode=0o700)
    path = runtime / "collection-ready.json"
    real_fsync = os.fsync
    calls = 0

    def fail_readiness_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected post-commit failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_readiness_directory_fsync)
    with pytest.raises(OxidizedPublicationAmbiguousError):
        publish_readiness(path, "a" * 64)
    assert path.is_file()
    assert readiness_ambiguity_path(path).is_file()
    with pytest.raises(ValueError, match="readiness rejected"):
        read_collection_ready(path, "a" * 64)
    monkeypatch.setattr(os, "fsync", real_fsync)
    publish_readiness(path, "a" * 64)
    assert not readiness_ambiguity_path(path).exists()


@pytest.mark.parametrize("mode", [0o644, 0o600])
def test_any_readiness_ambiguity_path_fails_closed(tmp_path: Path, mode: int) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    control = tmp_path / "control"
    control.mkdir(mode=0o700)
    path = runtime / "collection-ready.json"
    publish_readiness(path, "a" * 64)
    ambiguity = readiness_ambiguity_path(path)
    ambiguity.write_text("malformed")
    ambiguity.chmod(mode)
    with pytest.raises(ValueError, match="readiness rejected"):
        read_collection_ready(path, "a" * 64)


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
    assert "<key>Umask</key><integer>63</integer>" in script
    assert 'chmod 0600 "${logfile}"' in script
    assert "/Users/netdevops/.local/lib/ncdp/oxidized-service" in script
    assert "uv run" not in script
    assert "--editable" not in script
    assert "oxidized-service.candidate" not in script
    assert "BAO_TOKEN" not in script
    assert "OPENBAO_TOKEN" not in script
    assert "docker.sock" not in script


def test_netbox_installer_is_external_private_and_pull_free() -> None:
    root = Path(__file__).parents[1]
    script = (root / "scripts/netbox/install_service.sh").read_text()
    assert "/Users/netdevops/.local/lib/ncdp/netbox-lab" in script
    assert "com.ncdp.netbox-lab" in script
    assert "<key>RunAtLoad</key><true/>" in script
    assert "<key>StartInterval</key><integer>300</integer>" in script
    assert "--editable" not in script
    assert "--no-deps dist/network_change_delivery-*.whl" in script
    assert "'httpx==0.28.1'" in script
    assert "docker compose down" not in script
    assert "rm -" not in script


def test_oxidized_updater_is_atomic_external_and_minimal() -> None:
    root = Path(__file__).parents[1]
    script = (root / "scripts/oxidized/update_service_runtime.sh").read_text()
    assert "/Users/netdevops/.local/lib/ncdp" in script
    assert "--no-deps dist/network_change_delivery-*.whl" in script
    assert "'httpx==0.28.1'" in script
    assert "'pydantic==2.13.4'" in script
    assert "'pyyaml==6.0.3'" in script
    assert 'mv "${ensure_candidate}" "${config_root}/ensure"' in script
    assert "--editable" not in script


def test_missing_docker_inspection_is_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "network_change_delivery.oxidized_reconciler._docker",
        lambda *_args, **_kwargs: "[]",
    )
    assert _inspect() is None


def test_reconciler_does_not_duplicate_fixed_docker_executable() -> None:
    source = (
        Path(__file__).parents[1] / "src/network_change_delivery/oxidized_reconciler.py"
    ).read_text()
    assert "_docker(*arguments[1:])" in source
