from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from network_change_delivery import observability_reconciler
from network_change_delivery.models import InventoryDevice
from network_change_delivery.observability_service import (
    BLACKBOX_CONTAINER,
    PROMETHEUS_CONTAINER,
    ObservabilityServiceError,
    invalidate_readiness,
    publish_readiness,
    read_readiness,
    verify_container_definitions,
)
from network_change_delivery.observability_targets import (
    TargetGenerationState,
    publish_generation,
    targets_from_inventory,
)

PROM_IMAGE = "sha256:" + "a" * 64
BLACKBOX_IMAGE = "sha256:" + "b" * 64
PROM_CONTAINER = "c" * 64
BLACKBOX_CONTAINER_ID = "d" * 64
COMMIT = "e" * 40
CONFIG_ROOT = Path("/private/config")
STATE_ROOT = Path("/private/state")


class Inventory:
    def resolve_managed_devices(self):
        return (
            InventoryDevice(
                name="core-02",
                host="192.0.2.14",
                port=22,
                platform="cisco_iosxe",
                expected_hostname="core-02",
                inventory_source="netbox",
                inventory_object_id="netbox:dcim.device:1",
            ),
            InventoryDevice(
                name="edge-junos-01",
                host="192.0.2.20",
                port=830,
                platform="junos",
                expected_hostname="edge-junos-01",
                inventory_source="netbox",
                inventory_object_id="netbox:dcim.device:2",
            ),
        )


def realization():
    return SimpleNamespace(
        lab_id="11111111-1111-1111-1111-111111111111",
        digest="sha256:" + "a" * 64,
    )


def active_generation(root: Path, now: datetime):
    return publish_generation(
        root,
        state=TargetGenerationState.ACTIVE,
        targets=targets_from_inventory(Inventory()),
        realization=realization(),
        now=now,
    )


def test_readiness_binds_generation_realization_containers_and_commit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external" / "observability"
    now = datetime(2026, 8, 28, tzinfo=UTC)
    generation = active_generation(root, now)
    marker = publish_readiness(
        root,
        generation,
        prometheus_container_id=PROM_CONTAINER,
        blackbox_container_id=BLACKBOX_CONTAINER_ID,
        source_commit=COMMIT,
        now=now,
    )
    assert (
        read_readiness(
            root,
            generation,
            prometheus_container_id=PROM_CONTAINER,
            blackbox_container_id=BLACKBOX_CONTAINER_ID,
            source_commit=COMMIT,
            now=now,
        )
        == marker
    )
    assert marker.realization_lab_id == realization().lab_id
    assert marker.targets == (
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
    )
    assert (root / "runtime/observability-ready.json").stat().st_mode & 0o777 == 0o600


def test_readiness_mismatch_expiry_guard_and_retirement_fail_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external" / "observability"
    now = datetime(2026, 8, 28, tzinfo=UTC)
    generation = active_generation(root, now)
    publish_readiness(
        root,
        generation,
        prometheus_container_id=PROM_CONTAINER,
        blackbox_container_id=BLACKBOX_CONTAINER_ID,
        source_commit=COMMIT,
        now=now,
    )
    with pytest.raises(ObservabilityServiceError):
        read_readiness(
            root,
            generation,
            prometheus_container_id="f" * 64,
            blackbox_container_id=BLACKBOX_CONTAINER_ID,
            source_commit=COMMIT,
            now=now,
        )
    with pytest.raises(ObservabilityServiceError):
        read_readiness(
            root,
            generation,
            prometheus_container_id=PROM_CONTAINER,
            blackbox_container_id=BLACKBOX_CONTAINER_ID,
            source_commit=COMMIT,
            now=now + timedelta(minutes=16),
        )
    guard = root / "control/readiness-publication-ambiguous"
    guard.write_text("AMBIGUOUS\n")
    guard.chmod(0o600)
    with pytest.raises(ObservabilityServiceError):
        read_readiness(
            root,
            generation,
            prometheus_container_id=PROM_CONTAINER,
            blackbox_container_id=BLACKBOX_CONTAINER_ID,
            source_commit=COMMIT,
            now=now,
        )
    invalidate_readiness(root / "runtime/observability-ready.json")
    assert not (root / "runtime/observability-ready.json").exists()


@pytest.mark.parametrize("source_commit", ["f" * 40, "not-a-commit"])
def test_readiness_rejects_wrong_or_malformed_expected_source_commit(
    tmp_path: Path, source_commit: str
) -> None:
    root = tmp_path / "external" / "observability"
    now = datetime(2026, 8, 28, tzinfo=UTC)
    generation = active_generation(root, now)
    publish_readiness(
        root,
        generation,
        prometheus_container_id=PROM_CONTAINER,
        blackbox_container_id=BLACKBOX_CONTAINER_ID,
        source_commit=COMMIT,
        now=now,
    )
    with pytest.raises(ObservabilityServiceError, match="readiness rejected"):
        read_readiness(
            root,
            generation,
            prometheus_container_id=PROM_CONTAINER,
            blackbox_container_id=BLACKBOX_CONTAINER_ID,
            source_commit=source_commit,
            now=now,
        )


def test_publish_readiness_rejects_malformed_source_commit(tmp_path: Path) -> None:
    root = tmp_path / "external" / "observability"
    now = datetime(2026, 8, 28, tzinfo=UTC)
    generation = active_generation(root, now)
    with pytest.raises(ValueError):
        publish_readiness(
            root,
            generation,
            prometheus_container_id=PROM_CONTAINER,
            blackbox_container_id=BLACKBOX_CONTAINER_ID,
            source_commit="not-a-commit",
            now=now,
        )


def inspection(name: str, image: str, identifier: str, *, prometheus: bool):
    binds = (
        [
            "/private/config/prometheus.yml:/etc/ncdp/prometheus.yml:ro",
            "/private/state/discovery:/etc/ncdp/targets:ro",
            "/private/state/prometheus:/prometheus:rw",
        ]
        if prometheus
        else ["/private/config/blackbox.yml:/etc/ncdp/blackbox.yml:ro"]
    )
    return {
        "Name": f"/{name}",
        "Id": identifier,
        "Image": image,
        "Config": {
            "User": f"{os.getuid()}:{os.getgid()}",
            "Labels": {"com.docker.compose.project": "ncdp-observability"},
        },
        "State": {"Running": True},
        "HostConfig": {
            "ReadonlyRootfs": True,
            "RestartPolicy": {"Name": "no"},
            "SecurityOpt": ["no-new-privileges:true"],
            "CapDrop": ["ALL"],
            "NetworkMode": "ncdp-observability-telemetry",
            "PortBindings": (
                {"9090/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9090"}]}
                if prometheus
                else {}
            ),
            "Binds": binds,
        },
    }


def test_container_definition_is_exact_nonroot_and_loopback_only() -> None:
    inspected = {
        PROMETHEUS_CONTAINER: inspection(
            PROMETHEUS_CONTAINER, PROM_IMAGE, PROM_CONTAINER, prometheus=True
        ),
        BLACKBOX_CONTAINER: inspection(
            BLACKBOX_CONTAINER,
            BLACKBOX_IMAGE,
            BLACKBOX_CONTAINER_ID,
            prometheus=False,
        ),
    }
    assert verify_container_definitions(
        inspected,
        prometheus_image_id=PROM_IMAGE,
        blackbox_image_id=BLACKBOX_IMAGE,
        config_root=CONFIG_ROOT,
        state_root=STATE_ROOT,
    ) == (PROM_CONTAINER, BLACKBOX_CONTAINER_ID)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item["HostConfig"].update(ReadonlyRootfs=False),
        lambda item: item["HostConfig"].update(CapDrop=[]),
        lambda item: item["HostConfig"].update(
            PortBindings={"9090/tcp": [{"HostIp": "0.0.0.0", "HostPort": "9090"}]}
        ),
        lambda item: item["Config"].update(User="65534:65534"),
        lambda item: item["HostConfig"].update(Binds=["/var/run/docker.sock:/x"]),
    ],
)
def test_container_security_drift_is_rejected(mutation) -> None:
    prometheus = inspection(
        PROMETHEUS_CONTAINER, PROM_IMAGE, PROM_CONTAINER, prometheus=True
    )
    mutation(prometheus)
    inspected = {
        PROMETHEUS_CONTAINER: prometheus,
        BLACKBOX_CONTAINER: inspection(
            BLACKBOX_CONTAINER,
            BLACKBOX_IMAGE,
            BLACKBOX_CONTAINER_ID,
            prometheus=False,
        ),
    }
    with pytest.raises(ObservabilityServiceError):
        verify_container_definitions(
            inspected,
            prometheus_image_id=PROM_IMAGE,
            blackbox_image_id=BLACKBOX_IMAGE,
            config_root=CONFIG_ROOT,
            state_root=STATE_ROOT,
        )


def test_runtime_configuration_freezes_relabel_security_and_retention() -> None:
    root = Path(__file__).parents[1]
    compose = (root / "infrastructure/observability/compose.yaml").read_text()
    prometheus = (root / "infrastructure/observability/prometheus.yml").read_text()
    blackbox = (root / "infrastructure/observability/blackbox.yml").read_text()
    for value in (
        "v3.14.0@sha256:5ce7540c",
        "v0.27.0@sha256:a50c4c0e",
        'restart: "no"',
        "read_only: true",
        "no-new-privileges:true",
        "127.0.0.1:9090:9090",
        "cap_drop:",
        "- ALL",
        "--storage.tsdb.retention.time=15d",
        "--storage.tsdb.retention.size=1GB",
    ):
        assert value in compose
    for forbidden in (
        "docker.sock",
        "/.ssh",
        "audit",
        "config-history",
        "OPENBAO",
        "NETBOX_TOKEN",
        "password",
    ):
        assert forbidden not in compose
    assert "__param_target" in prometheus
    assert "source_labels:" in prometheus
    assert "replacement: blackbox:9115" in prometheus
    assert "192.168.4." not in prometheus
    assert "prober: tcp" in blackbox
    assert "http" not in blackbox
    assert "icmp" not in blackbox


def test_installer_is_external_private_and_does_not_load_launchagent() -> None:
    root = Path(__file__).parents[1]
    script = (root / "scripts/observability/install_service.sh").read_text()
    assert "/Users/netdevops/.local/lib/ncdp" in script
    assert "observability-service-${commit}" in script
    assert "/Users/netdevops/.local/state/ncdp/observability" in script
    assert "/Users/netdevops/.config/ncdp/observability" in script
    assert "<key>RunAtLoad</key><true/>" in script
    assert "<key>StartInterval</key><integer>300</integer>" in script
    assert "chmod 0600" in script
    assert "bootstrap" not in script.casefold()
    assert "launchctl" not in script
    assert "ansible-galaxy" not in script
    assert "node.next" not in script
    assert '"${runtime}/bin/python" -c' in script
    assert " python -c" not in script


def _installer_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], dict[str, Path]]:
    root = Path(__file__).parents[1]
    work = tmp_path / "work"
    script_root = work / "scripts/observability"
    infrastructure = work / "infrastructure/observability"
    script_root.mkdir(parents=True)
    infrastructure.mkdir(parents=True)
    launchagents = tmp_path / "Library/LaunchAgents"
    launchagents.mkdir(parents=True)
    script = (root / "scripts/observability/install_service.sh").read_text()
    plist = launchagents / "com.ncdp.observability.plist"
    script = script.replace(
        "plist=/Users/netdevops/Library/LaunchAgents/com.ncdp.observability.plist",
        f"plist={plist}",
    )
    installer = script_root / "install_service.sh"
    installer.write_text(script)
    installer.chmod(0o700)
    for name in ("compose.yaml", "prometheus.yml", "blackbox.yml"):
        shutil.copy(root / "infrastructure/observability" / name, infrastructure / name)

    binaries = tmp_path / "bin"
    binaries.mkdir()
    for command in ("cat", "chmod", "cp", "grep", "mkdir", "rm", "rmdir", "touch"):
        executable = shutil.which(command)
        assert executable is not None
        (binaries / command).symlink_to(executable)
    (binaries / "id").write_text("#!/bin/sh\necho netdevops\n")
    (binaries / "id").chmod(0o700)
    image_id = "sha256:" + "a" * 64
    (binaries / "docker").write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  *Os*Architecture*) echo '{image_id} linux/arm64' ;;\n"
        f"  *) echo '{image_id}' ;;\n"
        "esac\n"
    )
    (binaries / "docker").chmod(0o700)
    runtime_python = tmp_path / "runtime-python"
    runtime_python.write_text(
        "#!/bin/sh\n"
        'case "$2" in\n'
        "  *authority.json*)\n"
        '    [ "${NCDP_TEST_FAIL_AUTHORITY:-0}" = 0 ] || exit 17\n'
        f'    exec {sys.executable} "$@"\n'
        "    ;;\n"
        "  *publish_generation*) exit 0 ;;\n"
        "  *) exit 19 ;;\n"
        "esac\n"
    )
    runtime_python.chmod(0o700)
    (binaries / "uv").write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  venv)\n"
        "    runtime=$4\n"
        '    mkdir -p "${runtime}/bin"\n'
        '    cp "${NCDP_TEST_RUNTIME_PYTHON}" "${runtime}/bin/python"\n'
        '    chmod 0700 "${runtime}/bin/python"\n'
        "    ;;\n"
        "  build)\n"
        "    mkdir -p dist\n"
        "    touch dist/network_change_delivery-0.1.0-py3-none-any.whl\n"
        "    ;;\n"
        "  pip) exit 0 ;;\n"
        "  *) exit 18 ;;\n"
        "esac\n"
    )
    (binaries / "uv").chmod(0o700)
    (binaries / "plutil").write_text('#!/bin/sh\n[ -f "$2" ]\n')
    (binaries / "plutil").chmod(0o700)

    paths = {
        "state": tmp_path / "external/state/observability",
        "config": tmp_path / "external/config/observability",
        "service_parent": tmp_path / "external/lib/ncdp",
        "plist": plist,
    }
    paths["runtime"] = paths["service_parent"] / f"observability-service-{'a' * 40}"
    paths["service_parent"].mkdir(parents=True)
    sentinel = paths["service_parent"] / "unrelated-runtime"
    sentinel.write_text("preserve\n")
    environment = {
        "PATH": str(binaries),
        "NCDP_SOURCE_COMMIT": "a" * 40,
        "NCDP_OBSERVABILITY_STATE_ROOT": str(paths["state"]),
        "NCDP_OBSERVABILITY_CONFIG_ROOT": str(paths["config"]),
        "NCDP_OBSERVABILITY_SERVICE_PARENT": str(paths["service_parent"]),
        "NCDP_OBSERVABILITY_NETBOX_TOKEN": "test-token",
        "NCDP_OBSERVABILITY_CML_ADDRESS": "https://cml.invalid",
        "NCDP_OBSERVABILITY_CML_CACERT": "test-certificate",
        "NCDP_OBSERVABILITY_CML_USERNAME": "test-user",
        "NCDP_OBSERVABILITY_CML_PASSWORD": "test-password",
        "NCDP_TEST_RUNTIME_PYTHON": str(runtime_python),
    }
    assert shutil.which("python", path=environment["PATH"]) is None
    return installer, environment, paths


def test_installer_uses_runtime_python_without_host_python(tmp_path: Path) -> None:
    installer, environment, paths = _installer_fixture(tmp_path)
    result = subprocess.run(
        [str(installer)],
        cwd=installer.parents[2],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (paths["config"] / "authority.json").is_file()
    assert paths["runtime"].is_dir()
    assert paths["plist"].is_file()
    assert (paths["service_parent"] / "unrelated-runtime").is_file()


def test_failed_first_install_cleans_only_new_state_and_can_retry(
    tmp_path: Path,
) -> None:
    installer, environment, paths = _installer_fixture(tmp_path)
    failed = subprocess.run(
        [str(installer)],
        cwd=installer.parents[2],
        env={**environment, "NCDP_TEST_FAIL_AUTHORITY": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert failed.returncode == 17
    assert not paths["state"].exists()
    assert not paths["config"].exists()
    assert not paths["runtime"].exists()
    assert not paths["plist"].exists()
    assert (paths["service_parent"] / "unrelated-runtime").read_text() == "preserve\n"

    retry = subprocess.run(
        [str(installer)],
        cwd=installer.parents[2],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert retry.returncode == 0, retry.stderr
    assert paths["runtime"].is_dir()
    assert paths["plist"].is_file()


def test_first_install_rejects_and_preserves_preexisting_state(tmp_path: Path) -> None:
    installer, environment, paths = _installer_fixture(tmp_path)
    paths["state"].mkdir(parents=True)
    existing = paths["state"] / "prometheus-history"
    existing.write_text("preserve\n")

    result = subprocess.run(
        [str(installer)],
        cwd=installer.parents[2],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert existing.read_text() == "preserve\n"
    assert not paths["config"].exists()
    assert not paths["runtime"].exists()
    assert not paths["plist"].exists()


def test_retirement_order_invalidates_authorization_before_empty_targets() -> None:
    root = Path(__file__).parents[1]
    script = (root / "scripts/observability/retire_cml_realization.py").read_text()
    readiness = script.index("invalidate_readiness(")
    admission = script.index("retire_admission(")
    empty_targets = script.index("publish_generation(")
    settled = script.index("wait_targets_retired(")
    assert readiness < admission < empty_targets < settled


def test_update_runtime_is_external_noneditable_and_preserves_authority() -> None:
    root = Path(__file__).parents[1]
    script = (root / "scripts/observability/update_service_runtime.sh").read_text()
    assert "observability-service-${commit}" in script
    assert "--no-deps" in script
    assert "pip install -e" not in script
    assert "authority.json" not in script
    assert "netbox-token" not in script
    assert "launchctl" not in script
    assert "runtime-update-in-progress" in script
    assert "runtime-transition.lock" in script
    lock = script.index('mkdir "${lock}"')
    invalidate = script.index('rm -f "${state_root}/runtime/observability-ready.json"')
    first_switch = script.index('mv "${config_root}/.prometheus.yml.candidate"')
    ensure_switch = script.index('mv "${config_root}/.ensure.candidate"')
    unlock = script.index('rmdir "${lock}"')
    assert lock < invalidate < first_switch < ensure_switch < unlock
    assert "NCDP_OBSERVABILITY_RUNTIME_COMMIT=${commit}" in script
    assert "${#commit}" in script


def test_runtime_source_commit_binds_entrypoint_private_authority_and_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "external" / "observability"
    config.mkdir(parents=True, mode=0o700)
    source = config / "source-commit"
    source.write_text(f"{COMMIT}\n")
    source.chmod(0o600)
    monkeypatch.setattr(observability_reconciler, "CONFIG_ROOT", config)
    monkeypatch.setenv("NCDP_OBSERVABILITY_RUNTIME_COMMIT", COMMIT)
    assert observability_reconciler._runtime_source_commit() == COMMIT

    monkeypatch.setenv("NCDP_OBSERVABILITY_RUNTIME_COMMIT", "f" * 40)
    with pytest.raises(ObservabilityServiceError, match="runtime identity"):
        observability_reconciler._runtime_source_commit()
    monkeypatch.setenv("NCDP_OBSERVABILITY_RUNTIME_COMMIT", COMMIT)
    guard = config / "runtime-update-in-progress"
    guard.write_text(f"{COMMIT}\n")
    guard.chmod(0o600)
    with pytest.raises(ObservabilityServiceError, match="update ambiguous"):
        observability_reconciler._runtime_source_commit()


def test_runtime_transition_lock_is_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "external" / "observability"
    config.mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(observability_reconciler, "CONFIG_ROOT", config)
    with observability_reconciler._runtime_transition_lock():
        assert (config / "runtime-transition.lock").is_dir()
        with (
            pytest.raises(ObservabilityServiceError, match="transition ambiguous"),
            observability_reconciler._runtime_transition_lock(),
        ):
            pass
    assert not (config / "runtime-transition.lock").exists()


def test_reconciler_uses_no_openbao_ssh_or_configuration_collection() -> None:
    source = (
        Path(__file__).parents[1]
        / "src/network_change_delivery/observability_reconciler.py"
    ).read_text()
    lowered = source.casefold()
    for forbidden in (
        "openbao",
        "known_hosts",
        "node.next",
        "oxidized",
        "ansible",
        "netconf",
        "ssh",
        "configuration",
        "diff",
    ):
        assert forbidden not in lowered
    assert "NetBoxInventoryProvider" in source
    assert "CmlRealizationAuthority" in source
