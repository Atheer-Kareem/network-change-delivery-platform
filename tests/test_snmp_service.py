from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from network_change_delivery.snmp_mib import EXPORTER_IMAGE
from network_change_delivery.snmp_service import (
    SNMP_AUTH_TARGET,
    SNMP_EXPORTER_CONTAINER,
    SNMP_EXPORTER_SERVICE,
    SNMP_MODULE_TARGET,
    SnmpServiceError,
    verify_snmp_exporter_definition,
)

IMAGE_ID = "sha256:" + "a" * 64
CONTAINER_ID = "b" * 64
MODULE_ROOT = Path("/private/modules")
AUTH_ROOT = Path("/private/auth")


def inspection() -> dict[str, object]:
    return {
        "Name": f"/{SNMP_EXPORTER_CONTAINER}",
        "Id": CONTAINER_ID,
        "Image": IMAGE_ID,
        "Config": {
            "Image": EXPORTER_IMAGE,
            "User": f"{os.getuid()}:{os.getgid()}",
            "Env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            ],
            "Cmd": [
                f"--config.file={SNMP_MODULE_TARGET}/snmp-modules.yml",
                f"--config.file={SNMP_AUTH_TARGET}/snmp-auth.yml",
            ],
            "Labels": {
                "com.docker.compose.project": "synthetic-project",
                "com.docker.compose.service": SNMP_EXPORTER_SERVICE,
            },
        },
        "State": {"Running": True},
        "NetworkSettings": {"Networks": {"synthetic-snmp": {}}},
        "HostConfig": {
            "ReadonlyRootfs": True,
            "RestartPolicy": {"Name": "no"},
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "NetworkMode": "synthetic-snmp",
            "PortBindings": {},
            "Binds": [
                f"{MODULE_ROOT}:{SNMP_MODULE_TARGET}:ro",
                f"{AUTH_ROOT}:{SNMP_AUTH_TARGET}:ro",
            ],
        },
    }


def verify(value: dict[str, object]) -> str:
    return verify_snmp_exporter_definition(
        value,
        image_id=IMAGE_ID,
        module_root=MODULE_ROOT,
        auth_root=AUTH_ROOT,
        project_name="synthetic-project",
        network_name="synthetic-snmp",
    )


def test_exact_private_exporter_definition_is_accepted() -> None:
    assert verify(inspection()) == CONTAINER_ID


def test_snmp_overlay_is_explicit_private_and_does_not_change_base_runtime() -> None:
    root = Path(__file__).parents[1] / "infrastructure/observability"
    base = yaml.safe_load((root / "compose.yaml").read_text())
    overlay = yaml.safe_load((root / "compose-snmp.yaml").read_text())
    assert set(base["services"]) == {
        "prometheus",
        "blackbox",
        "grafana",
        "alertmanager",
        "receiver",
    }
    exporter = overlay["services"]["snmp_exporter"]
    assert exporter["image"] == EXPORTER_IMAGE
    assert exporter["restart"] == "no"
    assert exporter["read_only"] is True
    assert exporter["cap_drop"] == ["ALL"]
    assert exporter["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in exporter
    assert "environment" not in exporter
    assert exporter["networks"] == ["snmp"]
    assert len(exporter["volumes"]) == 2
    assert all(mount["read_only"] is True for mount in exporter["volumes"])
    assert overlay["networks"]["snmp"]["internal"] is True
    assert set(overlay["services"]["prometheus"]["networks"]) == {
        "telemetry",
        "snmp",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item["HostConfig"].update(ReadonlyRootfs=False),
        lambda item: item["HostConfig"].update(CapDrop=[]),
        lambda item: item["HostConfig"].update(
            PortBindings={"9116/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9116"}]}
        ),
        lambda item: item["HostConfig"].update(
            Binds=["/var/run/docker.sock:/var/run/docker.sock"]
        ),
        lambda item: item["NetworkSettings"].update(
            Networks={"synthetic-snmp": {}, "unexpected": {}}
        ),
        lambda item: item["Config"].update(
            Cmd=["--config.expand-environment-variables"]
        ),
        lambda item: item["Config"].update(Env=["SNMP_USERNAME=controlled-principal"]),
        lambda item: item["Config"].update(User=f"{os.getuid() + 1}:{os.getgid() + 1}"),
        lambda item: item["Config"].update(Image="prom/snmp-exporter:latest"),
    ],
)
def test_exporter_authority_and_security_drift_fail_closed(mutation) -> None:
    value = inspection()
    mutation(value)
    with pytest.raises(SnmpServiceError):
        verify(value)
