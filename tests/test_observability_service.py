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
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
)
from network_change_delivery.observability_realization import (
    ObservabilityRealizationError,
)
from network_change_delivery.observability_service import (
    ALERTMANAGER_CONTAINER,
    BLACKBOX_CONTAINER,
    EXPECTED_IMAGE_REFERENCES,
    EXPECTED_SERVICE_NAMES,
    GRAFANA_CONTAINER,
    PROMETHEUS_CONTAINER,
    RECEIVER_CONTAINER,
    ObservabilityServiceError,
    invalidate_readiness,
    publish_readiness,
    read_readiness,
    verify_container_definitions,
)
from network_change_delivery.observability_targets import (
    TargetFailureClassification,
    TargetGenerationState,
    publish_generation,
    read_generation,
    targets_from_inventory,
)

PROM_IMAGE = "sha256:" + "a" * 64
BLACKBOX_IMAGE = "sha256:" + "b" * 64
GRAFANA_IMAGE = "sha256:" + "c" * 64
ALERTMANAGER_IMAGE = "sha256:" + "d" * 64
RECEIVER_IMAGE = "sha256:" + "e" * 64
PROM_CONTAINER = "c" * 64
BLACKBOX_CONTAINER_ID = "d" * 64
GRAFANA_CONTAINER_ID = "e" * 64
ALERTMANAGER_CONTAINER_ID = "f" * 64
RECEIVER_CONTAINER_ID = "a" * 64
COMMIT = "e" * 40
CONFIG_ROOT = Path("/private/config")
STATE_ROOT = Path("/private/state")
RUNTIME_ROOT = Path("/private/runtime")


class Inventory:
    def resolve_profiled_population(self):
        def device(identity, name, slug, network_os, profile, host, port):
            class Device(SimpleNamespace):
                def live_read_only_target(self):
                    return SimpleNamespace(host=self.host, port=self.port)

            return Device(
                inventory_object_id=identity,
                logical_name=name,
                platform=SimpleNamespace(slug=slug),
                network_os=network_os,
                automation_profile_id=profile,
                host=host,
                port=port,
            )

        return SimpleNamespace(
            devices=(
                device(
                    "netbox:dcim.device:1",
                    "core-02",
                    "cisco-ios-xe",
                    NetworkOS.IOSXE,
                    AutomationProfileID.CAT8000V_IOSXE,
                    "192.0.2.14",
                    22,
                ),
                device(
                    "netbox:dcim.device:2",
                    "edge-junos-01",
                    "juniper-junos",
                    NetworkOS.JUNOS,
                    AutomationProfileID.VJUNOS_ROUTER,
                    "192.0.2.20",
                    830,
                ),
                device(
                    "netbox:dcim.device:8",
                    "transit-ios-01",
                    "cisco-ios",
                    NetworkOS.IOS,
                    AutomationProfileID.IOSV_159_3_M12,
                    "192.0.2.16",
                    22,
                ),
                device(
                    "netbox:dcim.device:9",
                    "access-sw-01",
                    "cisco-ios",
                    NetworkOS.IOS,
                    AutomationProfileID.IOSVL2_2020,
                    "192.0.2.17",
                    22,
                ),
            )
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
        "netbox:dcim.device:8",
        "netbox:dcim.device:9",
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


def inspection(name: str, image: str, identifier: str):
    binds = {
        PROMETHEUS_CONTAINER: [
            "/private/config/prometheus.yml:/etc/ncdp/prometheus.yml:ro",
            "/private/runtime/rules:/etc/ncdp/rules:ro",
            "/private/state/discovery:/etc/ncdp/targets:ro",
            "/private/state/prometheus:/prometheus:rw",
        ],
        BLACKBOX_CONTAINER: ["/private/config/blackbox.yml:/etc/ncdp/blackbox.yml:ro"],
        GRAFANA_CONTAINER: [
            "/private/runtime/grafana/provisioning:/etc/grafana/provisioning:ro",
            "/private/runtime/grafana/dashboards:/etc/grafana/dashboards:ro",
            "/private/state/grafana:/var/lib/grafana:rw",
        ],
        ALERTMANAGER_CONTAINER: [
            "/private/runtime/alertmanager/alertmanager.yml:/etc/ncdp/alertmanager.yml:ro",
            "/private/state/alertmanager:/alertmanager:rw",
        ],
        RECEIVER_CONTAINER: [
            "/private/runtime/receiver/demo_receiver.py:/opt/ncdp/demo_receiver.py:ro"
        ],
    }[name]
    ports = {
        PROMETHEUS_CONTAINER: {
            "9090/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9090"}]
        },
        GRAFANA_CONTAINER: {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3000"}]},
    }.get(name, {})
    return {
        "Name": f"/{name}",
        "Id": identifier,
        "Image": image,
        "Config": {
            "User": f"{os.getuid()}:{os.getgid()}",
            "Image": EXPECTED_IMAGE_REFERENCES[name],
            "Labels": {
                "com.docker.compose.project": "ncdp-observability",
                "com.docker.compose.service": EXPECTED_SERVICE_NAMES[name],
            },
        },
        "State": {"Running": True},
        "NetworkSettings": {"Networks": {"ncdp-observability-telemetry": {}}},
        "HostConfig": {
            "ReadonlyRootfs": True,
            "RestartPolicy": {"Name": "no"},
            "SecurityOpt": ["no-new-privileges:true"],
            "CapDrop": ["ALL"],
            "NetworkMode": "ncdp-observability-telemetry",
            "PortBindings": ports,
            "Binds": binds,
        },
    }


def valid_inspections():
    return {
        PROMETHEUS_CONTAINER: inspection(
            PROMETHEUS_CONTAINER, PROM_IMAGE, PROM_CONTAINER
        ),
        BLACKBOX_CONTAINER: inspection(
            BLACKBOX_CONTAINER, BLACKBOX_IMAGE, BLACKBOX_CONTAINER_ID
        ),
        GRAFANA_CONTAINER: inspection(
            GRAFANA_CONTAINER, GRAFANA_IMAGE, GRAFANA_CONTAINER_ID
        ),
        ALERTMANAGER_CONTAINER: inspection(
            ALERTMANAGER_CONTAINER,
            ALERTMANAGER_IMAGE,
            ALERTMANAGER_CONTAINER_ID,
        ),
        RECEIVER_CONTAINER: inspection(
            RECEIVER_CONTAINER, RECEIVER_IMAGE, RECEIVER_CONTAINER_ID
        ),
    }


def verify_inspections(inspected):
    return verify_container_definitions(
        inspected,
        prometheus_image_id=PROM_IMAGE,
        blackbox_image_id=BLACKBOX_IMAGE,
        grafana_image_id=GRAFANA_IMAGE,
        alertmanager_image_id=ALERTMANAGER_IMAGE,
        receiver_image_id=RECEIVER_IMAGE,
        config_root=CONFIG_ROOT,
        state_root=STATE_ROOT,
        runtime_root=RUNTIME_ROOT,
    )


def test_container_definition_is_exact_nonroot_and_loopback_only() -> None:
    assert verify_inspections(valid_inspections()) == (
        PROM_CONTAINER,
        BLACKBOX_CONTAINER_ID,
    )


def test_five_service_verifier_accepts_only_opted_in_prometheus_network() -> None:
    inspected = valid_inspections()
    prometheus = inspected[PROMETHEUS_CONTAINER]
    prometheus["HostConfig"]["NetworkMode"] = "synthetic-snmp"
    prometheus["NetworkSettings"]["Networks"]["synthetic-snmp"] = {}
    assert verify_container_definitions(
        inspected,
        prometheus_image_id=PROM_IMAGE,
        blackbox_image_id=BLACKBOX_IMAGE,
        grafana_image_id=GRAFANA_IMAGE,
        alertmanager_image_id=ALERTMANAGER_IMAGE,
        receiver_image_id=RECEIVER_IMAGE,
        config_root=CONFIG_ROOT,
        state_root=STATE_ROOT,
        runtime_root=RUNTIME_ROOT,
        prometheus_additional_networks=frozenset({"synthetic-snmp"}),
    ) == (PROM_CONTAINER, BLACKBOX_CONTAINER_ID)


@pytest.mark.parametrize(
    "name,mutation",
    [
        (
            PROMETHEUS_CONTAINER,
            lambda item: item["HostConfig"].update(ReadonlyRootfs=False),
        ),
        (BLACKBOX_CONTAINER, lambda item: item["HostConfig"].update(CapDrop=[])),
        (
            GRAFANA_CONTAINER,
            lambda item: item["HostConfig"].update(
                PortBindings={"9090/tcp": [{"HostIp": "0.0.0.0", "HostPort": "9090"}]}
            ),
        ),
        (
            ALERTMANAGER_CONTAINER,
            lambda item: item["Config"].update(
                User=f"{os.getuid() ^ 1}:{os.getgid() ^ 1}"
            ),
        ),
        (
            RECEIVER_CONTAINER,
            lambda item: item["HostConfig"].update(Binds=["/var/run/docker.sock:/x"]),
        ),
        (
            GRAFANA_CONTAINER,
            lambda item: item["Config"].update(Image="grafana/grafana:latest"),
        ),
        (
            RECEIVER_CONTAINER,
            lambda item: item["NetworkSettings"].update(
                Networks={
                    "ncdp-observability-telemetry": {},
                    "unexpected-network": {},
                }
            ),
        ),
        (
            PROMETHEUS_CONTAINER,
            lambda item: item["HostConfig"].update(
                Binds=[
                    bind
                    for bind in item["HostConfig"]["Binds"]
                    if "/etc/ncdp/rules" not in bind
                ]
            ),
        ),
    ],
)
def test_container_security_drift_is_rejected(name, mutation) -> None:
    inspected = valid_inspections()
    mutation(inspected[name])
    with pytest.raises(ObservabilityServiceError):
        verify_inspections(inspected)


def test_incomplete_five_service_runtime_is_rejected() -> None:
    inspected = valid_inspections()
    inspected.pop(RECEIVER_CONTAINER)
    with pytest.raises(ObservabilityServiceError, match="container inspection"):
        verify_inspections(inspected)


def test_runtime_configuration_freezes_relabel_security_and_retention() -> None:
    root = Path(__file__).parents[1]
    compose = (root / "infrastructure/observability/compose.yaml").read_text()
    prometheus = (root / "infrastructure/observability/prometheus.yml").read_text()
    blackbox = (root / "infrastructure/observability/blackbox.yml").read_text()
    verifier = (root / "scripts/observability/verify_runtime.sh").read_text()
    for value in (
        "v3.14.0@sha256:5ce7540c",
        "v0.27.0@sha256:a50c4c0e",
        'restart: "no"',
        "read_only: true",
        "no-new-privileges:true",
        "127.0.0.1:${NCDP_PROMETHEUS_PORT:-9090}:9090",
        "127.0.0.1:${NCDP_GRAFANA_PORT:-3000}:3000",
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
    assert "verify_container_definitions(" in verifier
    assert 'docker inspect "${containers[@]}"' in verifier


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
    for relative in (
        "rules/11b-alerts.yml",
        "alertmanager.yml",
        "grafana/provisioning/datasources/prometheus.yml",
        "grafana/provisioning/dashboards/dashboards.yml",
        "grafana/dashboards/ncdp-management-reachability.json",
    ):
        destination = infrastructure / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(root / "infrastructure/observability" / relative, destination)
    shutil.copy(root / "scripts/observability/demo_receiver.py", script_root)

    binaries = tmp_path / "bin"
    binaries.mkdir()
    for command in (
        "cat",
        "chmod",
        "cp",
        "grep",
        "mkdir",
        "mv",
        "rm",
        "rmdir",
        "touch",
    ):
        executable = shutil.which(command)
        assert executable is not None
        (binaries / command).symlink_to(executable)
    (binaries / "id").write_text("#!/bin/sh\necho netdevops\n")
    (binaries / "id").chmod(0o700)
    image_id = "sha256:" + "a" * 64
    (binaries / "docker").write_text(
        "#!/bin/sh\n"
        'case "$*" in *"${NCDP_TEST_MISSING_IMAGE:-__never__}"*) exit 23 ;; esac\n'
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
    for name in (
        "prometheus-image-id",
        "blackbox-image-id",
        "grafana-image-id",
        "alertmanager-image-id",
        "receiver-image-id",
    ):
        image_id = paths["config"] / name
        assert image_id.read_text() == f"sha256:{'a' * 64}\n"
        assert image_id.stat().st_mode & 0o777 == 0o600
    for directory in ("grafana", "alertmanager"):
        path = paths["state"] / directory
        assert path.is_dir()
        assert path.stat().st_mode & 0o777 == 0o700
    for relative in (
        "rules/11b-alerts.yml",
        "alertmanager/alertmanager.yml",
        "grafana/provisioning/datasources/prometheus.yml",
        "grafana/provisioning/dashboards/dashboards.yml",
        "grafana/dashboards/ncdp-management-reachability.json",
        "receiver/demo_receiver.py",
    ):
        path = paths["runtime"] / relative
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600


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
    installer = (root / "scripts/observability/install_service.sh").read_text()
    compose = (root / "infrastructure/observability/compose.yaml").read_text()
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
    assert "docker pull" not in script
    for name in ("prometheus", "blackbox", "grafana", "alertmanager", "receiver"):
        assert f".{name}-image-id.candidate" in script
    for exact_ref in (
        "prom/prometheus:v3.14.0@sha256:5ce7540c3c00ef4ab0c9d2c995c6a5b9c421f44b4a115d97a2c7af3b1c21cbb0",
        "prom/blackbox-exporter:v0.27.0@sha256:a50c4c0eda297baa1678cd4dc4712a67fdea713b832d43ce7fcc5f9bea05094d",
        "grafana/grafana:12.1.1@sha256:a1701c2180249361737a99a01bc770db39381640e4d631825d38ff4535efa47d",
        "prom/alertmanager:v0.29.0@sha256:88743b63b3e09ea6e31e140ced5bf45f4a8e82c617c2a963f78841f4995ad1d7",
        "python:3.12.13-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a",
    ):
        assert exact_ref in script
        assert exact_ref in installer
        assert exact_ref in compose


def test_update_runtime_transitions_existing_11a_state_to_five_services(
    tmp_path: Path,
) -> None:
    installer, environment, paths = _installer_fixture(tmp_path)
    installed = subprocess.run(
        [str(installer)],
        cwd=installer.parents[2],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr

    for name in ("grafana-image-id", "alertmanager-image-id", "receiver-image-id"):
        (paths["config"] / name).unlink()
    shutil.rmtree(paths["state"] / "grafana")
    shutil.rmtree(paths["state"] / "alertmanager")
    authority = (paths["config"] / "authority.json").read_bytes()
    token = (paths["config"] / "netbox-token").read_bytes()

    root = Path(__file__).parents[1]
    updater = installer.parent / "update_service_runtime.sh"
    updater.write_text(
        (root / "scripts/observability/update_service_runtime.sh").read_text()
    )
    updater.chmod(0o700)
    updated_commit = "b" * 40
    result = subprocess.run(
        [str(updater)],
        cwd=updater.parents[2],
        env={**environment, "NCDP_SOURCE_COMMIT": updated_commit},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    updated_runtime = (
        paths["service_parent"] / f"observability-service-{updated_commit}"
    )
    assert (paths["config"] / "compose-path").read_text() == (
        f"{updated_runtime}/compose.yaml\n"
    )
    assert (paths["config"] / "source-commit").read_text() == f"{updated_commit}\n"
    assert (paths["config"] / "authority.json").read_bytes() == authority
    assert (paths["config"] / "netbox-token").read_bytes() == token
    for name in (
        "prometheus-image-id",
        "blackbox-image-id",
        "grafana-image-id",
        "alertmanager-image-id",
        "receiver-image-id",
    ):
        path = paths["config"] / name
        assert path.read_text() == f"sha256:{'a' * 64}\n"
        assert path.stat().st_mode & 0o777 == 0o600
    for directory in ("grafana", "alertmanager"):
        path = paths["state"] / directory
        assert path.is_dir()
        assert path.stat().st_mode & 0o777 == 0o700
    for relative in (
        "rules/11b-alerts.yml",
        "alertmanager/alertmanager.yml",
        "grafana/provisioning/datasources/prometheus.yml",
        "grafana/provisioning/dashboards/dashboards.yml",
        "grafana/dashboards/ncdp-management-reachability.json",
        "receiver/demo_receiver.py",
    ):
        path = updated_runtime / relative
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600
    assert not (paths["config"] / "runtime-update-in-progress").exists()
    assert not (paths["config"] / "runtime-transition.lock").exists()


def test_update_runtime_rejects_missing_pinned_image_before_switch(
    tmp_path: Path,
) -> None:
    installer, environment, paths = _installer_fixture(tmp_path)
    installed = subprocess.run(
        [str(installer)],
        cwd=installer.parents[2],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    compose_path = (paths["config"] / "compose-path").read_bytes()
    source_commit = (paths["config"] / "source-commit").read_bytes()

    root = Path(__file__).parents[1]
    updater = installer.parent / "update_service_runtime.sh"
    updater.write_text(
        (root / "scripts/observability/update_service_runtime.sh").read_text()
    )
    updater.chmod(0o700)
    result = subprocess.run(
        [str(updater)],
        cwd=updater.parents[2],
        env={
            **environment,
            "NCDP_SOURCE_COMMIT": "b" * 40,
            "NCDP_TEST_MISSING_IMAGE": "grafana/grafana",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert (paths["config"] / "compose-path").read_bytes() == compose_path
    assert (paths["config"] / "source-commit").read_bytes() == source_commit
    assert not (paths["config"] / "runtime-update-in-progress").exists()
    assert not (paths["config"] / "runtime-transition.lock").exists()


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


@pytest.mark.parametrize(
    "stage,expected_calls",
    (
        (
            observability_reconciler.AdmissionRefreshStage.SETTINGS,
            ["settings"],
        ),
        (
            observability_reconciler.AdmissionRefreshStage.ADMISSION_READ,
            ["settings", "admission_read"],
        ),
        (
            observability_reconciler.AdmissionRefreshStage.CML_REVALIDATION,
            ["settings", "admission_read", "cml_revalidation"],
        ),
        (
            observability_reconciler.AdmissionRefreshStage.ADMISSION_PUBLICATION,
            [
                "settings",
                "admission_read",
                "cml_revalidation",
                "authority_close",
                "admission_publication",
            ],
        ),
    ),
)
def test_refresh_stage_failure_remains_realization_rejected_and_stops_progression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: observability_reconciler.AdmissionRefreshStage,
    expected_calls: list[str],
) -> None:
    secret = "synthetic-secret-must-not-appear"
    state = tmp_path / "external" / "observability"
    state.mkdir(parents=True, mode=0o700)
    calls: list[str] = []
    settings = {
        "netbox_url": "https://netbox.invalid",
        "cml_address": "https://cml.invalid",
        "cml_certificate": "certificate",
        "cml_username": "username",
        "cml_password": "password",
    }
    previous = SimpleNamespace(
        lab_id="11111111-1111-1111-1111-111111111111",
        nodes=(
            SimpleNamespace(
                inventory_object_id="netbox:dcim.device:1",
                cml_node_id="22222222-2222-2222-2222-222222222222",
            ),
            SimpleNamespace(
                inventory_object_id="netbox:dcim.device:2",
                cml_node_id="33333333-3333-3333-3333-333333333333",
            ),
            SimpleNamespace(
                inventory_object_id="netbox:dcim.device:8",
                cml_node_id="44444444-4444-4444-4444-444444444444",
            ),
            SimpleNamespace(
                inventory_object_id="netbox:dcim.device:9",
                cml_node_id="55555555-5555-5555-5555-555555555555",
            ),
        ),
    )
    refreshed = SimpleNamespace(digest="sha256:" + "a" * 64)

    def settings_operation():
        calls.append("settings")
        if stage is observability_reconciler.AdmissionRefreshStage.SETTINGS:
            raise ObservabilityServiceError(secret)
        return settings

    def admission_read(_root):
        calls.append("admission_read")
        if stage is observability_reconciler.AdmissionRefreshStage.ADMISSION_READ:
            raise ObservabilityRealizationError(secret)
        return previous

    class Authority:
        def __init__(self, *_args):
            calls.append("cml_revalidation")
            if stage is observability_reconciler.AdmissionRefreshStage.CML_REVALIDATION:
                raise ObservabilityRealizationError(secret)

        def admit(self, _lab_id, _node_ids):
            return refreshed

        def close(self):
            calls.append("authority_close")

    def admission_publication(_root, _admission):
        calls.append("admission_publication")
        if (
            stage
            is observability_reconciler.AdmissionRefreshStage.ADMISSION_PUBLICATION
        ):
            raise ObservabilityRealizationError(secret)

    monkeypatch.setattr(observability_reconciler, "STATE_ROOT", state)
    monkeypatch.setattr(observability_reconciler, "_settings", settings_operation)
    monkeypatch.setattr(observability_reconciler, "read_admission", admission_read)
    monkeypatch.setattr(observability_reconciler, "CmlRealizationAuthority", Authority)
    monkeypatch.setattr(
        observability_reconciler, "publish_admission", admission_publication
    )
    monkeypatch.setattr(
        observability_reconciler, "_runtime_source_commit", lambda: COMMIT
    )
    monkeypatch.setattr(
        observability_reconciler,
        "validate_private_file",
        lambda *_args, **_kwargs: b"admission",
    )
    monkeypatch.setattr(
        observability_reconciler,
        "targets_from_inventory",
        lambda *_args: pytest.fail("target materialization followed refresh failure"),
    )

    with pytest.raises(observability_reconciler.AdmissionRefreshError) as caught:
        observability_reconciler._reconcile_locked()
    assert caught.value.stage is stage
    assert calls == expected_calls
    generation = read_generation(state)
    assert generation.state is TargetGenerationState.FAILED
    assert (
        generation.failure_classification
        is TargetFailureClassification.REALIZATION_REJECTED
    )
    assert generation.targets == ()
    assert not (state / "runtime/observability-ready.json").exists()
    serialized = (state / "runtime/target-generation.json").read_text()
    assert secret not in serialized


@pytest.mark.parametrize("stage", tuple(observability_reconciler.AdmissionRefreshStage))
def test_refresh_stage_diagnostic_is_finite_and_suppresses_underlying_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stage: observability_reconciler.AdmissionRefreshStage,
) -> None:
    secret = "synthetic-secret-must-not-appear"

    def fail():
        error = observability_reconciler.AdmissionRefreshError(stage)
        error.__cause__ = ValueError(secret)
        raise error

    monkeypatch.setattr(observability_reconciler, "reconcile", fail)
    monkeypatch.setattr(sys, "argv", ["ncdp-observability-service"])
    assert observability_reconciler.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"observability realization reconciliation failed stage={stage.value}\n"
    )
    assert secret not in captured.err


def test_successful_refresh_preserves_settings_validation_and_publication_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    settings = {
        "netbox_url": "https://netbox.invalid",
        "cml_address": "https://cml.invalid",
        "cml_certificate": "certificate",
        "cml_username": "username",
        "cml_password": "password",
    }
    previous = SimpleNamespace(
        lab_id="11111111-1111-1111-1111-111111111111",
        nodes=(
            SimpleNamespace(
                inventory_object_id="netbox:dcim.device:1",
                cml_node_id="22222222-2222-2222-2222-222222222222",
            ),
            SimpleNamespace(
                inventory_object_id="netbox:dcim.device:2",
                cml_node_id="33333333-3333-3333-3333-333333333333",
            ),
            SimpleNamespace(
                inventory_object_id="netbox:dcim.device:8",
                cml_node_id="44444444-4444-4444-4444-444444444444",
            ),
            SimpleNamespace(
                inventory_object_id="netbox:dcim.device:9",
                cml_node_id="55555555-5555-5555-5555-555555555555",
            ),
        ),
    )
    refreshed = SimpleNamespace(digest="sha256:" + "a" * 64)

    monkeypatch.setattr(
        observability_reconciler,
        "_settings",
        lambda: calls.append("settings") or settings,
    )
    monkeypatch.setattr(
        observability_reconciler,
        "read_admission",
        lambda _root: calls.append("admission_read") or previous,
    )

    class Authority:
        def __init__(self, *_args):
            calls.append("cml_authority")

        def admit(self, _lab_id, node_ids):
            calls.append("cml_admit")
            assert node_ids == {
                "netbox:dcim.device:1": "22222222-2222-2222-2222-222222222222",
                "netbox:dcim.device:2": "33333333-3333-3333-3333-333333333333",
                "netbox:dcim.device:8": "44444444-4444-4444-4444-444444444444",
                "netbox:dcim.device:9": "55555555-5555-5555-5555-555555555555",
            }
            return refreshed

        def close(self):
            calls.append("cml_close")

    monkeypatch.setattr(observability_reconciler, "CmlRealizationAuthority", Authority)
    monkeypatch.setattr(
        observability_reconciler,
        "publish_admission",
        lambda _root, _admission: calls.append("admission_publication"),
    )
    assert observability_reconciler._refresh_admission() == (settings, refreshed)
    assert calls == [
        "settings",
        "admission_read",
        "cml_authority",
        "cml_admit",
        "cml_close",
        "admission_publication",
    ]


def test_successful_refresh_still_materializes_targets_and_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "external" / "observability"
    state.mkdir(parents=True, mode=0o700)
    calls: list[str] = []
    settings = {"netbox_url": "https://netbox.invalid"}
    admission = realization()
    generation = SimpleNamespace(digest="sha256:" + "b" * 64)
    verified_containers: dict[str, object] = {}

    monkeypatch.setattr(observability_reconciler, "STATE_ROOT", state)
    monkeypatch.setattr(
        observability_reconciler,
        "validate_private_file",
        lambda *_args, **_kwargs: b"private-input",
    )
    monkeypatch.setattr(
        observability_reconciler,
        "_runtime_source_commit",
        lambda: calls.append("source_commit") or COMMIT,
    )
    monkeypatch.setattr(
        observability_reconciler,
        "_refresh_admission",
        lambda: calls.append("refresh") or (settings, admission),
    )
    monkeypatch.setattr(
        observability_reconciler,
        "NetBoxProfileInventoryProvider",
        lambda *_args: calls.append("inventory_provider") or Inventory(),
    )
    monkeypatch.setattr(
        observability_reconciler,
        "targets_from_inventory",
        lambda _inventory: calls.append("targets") or ("target",),
    )

    def generation_publication(_root, *, state, targets, realization):
        calls.append("generation")
        assert state is TargetGenerationState.ACTIVE
        assert targets == ("target",)
        assert realization is admission
        return generation

    monkeypatch.setattr(
        observability_reconciler, "publish_generation", generation_publication
    )
    monkeypatch.setattr(
        observability_reconciler,
        "run_compose",
        lambda *_args: calls.append("compose"),
    )
    monkeypatch.setattr(
        observability_reconciler,
        "inspect_containers",
        lambda: calls.append("inspect") or {},
    )

    def verify_containers(_inspected, **kwargs):
        calls.append("verify_containers")
        verified_containers.update(kwargs)
        return PROM_CONTAINER, BLACKBOX_CONTAINER_ID

    monkeypatch.setattr(
        observability_reconciler,
        "verify_container_definitions",
        verify_containers,
    )
    monkeypatch.setattr(
        observability_reconciler,
        "wait_service_health",
        lambda **_kwargs: calls.append("health"),
    )
    monkeypatch.setattr(
        observability_reconciler,
        "publish_readiness",
        lambda *_args, **_kwargs: calls.append("readiness"),
    )

    assert observability_reconciler._reconcile_locked() == generation.digest
    assert calls == [
        "source_commit",
        "refresh",
        "inventory_provider",
        "targets",
        "generation",
        "compose",
        "inspect",
        "verify_containers",
        "health",
        "source_commit",
        "readiness",
    ]
    assert set(verified_containers) == {
        "prometheus_image_id",
        "blackbox_image_id",
        "grafana_image_id",
        "alertmanager_image_id",
        "receiver_image_id",
        "config_root",
        "state_root",
        "runtime_root",
    }


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
    assert "NetBoxProfileInventoryProvider" in source
    assert "CmlRealizationAuthority" in source
