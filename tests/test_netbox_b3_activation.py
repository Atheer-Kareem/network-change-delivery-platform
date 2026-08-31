"""Detour B3-4 exact NetBox activation operator tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/netbox/activate_b3_profiled_devices.py"


def load_activation() -> ModuleType:
    spec = importlib.util.spec_from_file_location("netbox_b3_activation", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def container_payload(host_ip: str = "127.0.0.1") -> str:
    return json.dumps(
        [
            {
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "netbox-docker",
                        "com.docker.compose.service": "netbox",
                    }
                },
                "State": {"Running": True},
                "NetworkSettings": {
                    "Ports": {"8080/tcp": [{"HostIp": host_ip, "HostPort": "8000"}]}
                },
            }
        ]
    )


def test_activation_scope_is_exact_devices_8_and_9() -> None:
    activation = load_activation()
    assert activation.DEVICE_SPECS == {
        8: {
            "name": "transit-ios-01",
            "role": "transit",
            "device_type": "iosv-159-3-m12",
            "management_interface": "GigabitEthernet0/0",
            "live": "192.168.4.16/24",
            "staging": "192.168.4.31/24",
        },
        9: {
            "name": "access-sw-01",
            "role": "access",
            "device_type": "iosvl2-2020",
            "management_interface": "GigabitEthernet0/0",
            "live": "192.168.4.17/24",
            "staging": "192.168.4.32/24",
        },
    }
    source = SCRIPT.read_text()
    assert 'device.tags.filter(slug="ncdp-managed").exists()' in source
    assert ".delete(" not in source
    assert "OpenBao" not in source
    assert "CML2_" not in source
    assert "/api/v0/labs" not in source


def test_activation_requires_exact_loopback_netbox_container() -> None:
    activation = load_activation()
    activation.validate_container_identity(container_payload())
    with pytest.raises(activation.ActivationError, match="boundary"):
        activation.validate_container_identity(container_payload("0.0.0.0"))


def test_operator_uses_reviewed_source_and_bounds_admin_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activation = load_activation()
    calls = 0

    def run(arguments: list[str], **_kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(arguments, 0, container_payload(), "")
        payload = {"schema_version": "1", "devices": []}
        return subprocess.CompletedProcess(
            arguments,
            0,
            f"{activation.RESULT_PREFIX}{json.dumps(payload)}\n",
            "",
        )

    monkeypatch.setattr(activation.subprocess, "run", run)
    assert activation.run_operator_activation() == {
        "schema_version": "1",
        "devices": [],
    }

    def fail(arguments: list[str], **_kwargs: object):
        nonlocal calls
        calls += 1
        if calls % 2 == 1:
            return subprocess.CompletedProcess(arguments, 0, container_payload(), "")
        return subprocess.CompletedProcess(arguments, 1, "", "sensitive-admin-output")

    calls = 0
    monkeypatch.setattr(activation.subprocess, "run", fail)
    with pytest.raises(activation.ActivationError) as caught:
        activation.run_operator_activation()
    assert "sensitive-admin-output" not in str(caught.value)
