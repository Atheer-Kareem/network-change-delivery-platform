"""Deterministic deployment Ansible runtime prerequisite tests."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

import network_change_delivery.ansible_adapter as adapter_module
from network_change_delivery.ansible_adapter import (
    DeploymentRuntimeError,
    effective_ansible_collection_path,
    verify_deployment_ansible_runtime,
)

PINS = (("ansible.netcommon", "8.6.0"), ("cisco.ios", "11.4.2"))


@pytest.fixture(autouse=True)
def isolated_system_collection_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        adapter_module,
        "SYSTEM_ANSIBLE_COLLECTIONS",
        tmp_path / "isolated-system-collections",
    )


def write_requirements(root: Path, contents: str | None = None) -> None:
    requirements = root / "ansible" / "requirements.yml"
    requirements.parent.mkdir(parents=True)
    requirements.write_text(
        contents
        or """---
collections:
  - name: ansible.netcommon
    version: 8.6.0
  - name: cisco.ios
    version: 11.4.2
""",
        encoding="utf-8",
    )


def install_manifest(
    collection_root: Path,
    name: str,
    version: str,
    *,
    contents: str | None = None,
) -> None:
    namespace, collection = name.split(".")
    manifest = (
        collection_root
        / "ansible_collections"
        / namespace
        / collection
        / "MANIFEST.json"
    )
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        contents
        or json.dumps(
            {
                "collection_info": {
                    "namespace": namespace,
                    "name": collection,
                    "version": version,
                }
            }
        ),
        encoding="utf-8",
    )


def complete_runtime(root: Path, collection_root: Path) -> None:
    write_requirements(root)
    for name, version in PINS:
        install_manifest(collection_root, name, version)


def test_exact_pinned_collections_in_default_repository_path_pass(
    tmp_path: Path,
) -> None:
    collection_root = tmp_path / ".ansible" / "collections"
    complete_runtime(tmp_path, collection_root)
    assert verify_deployment_ansible_runtime(tmp_path, {}) == PINS
    assert effective_ansible_collection_path(tmp_path, {}).split(":")[0] == str(
        collection_root
    )


def test_explicit_collection_path_is_honored(tmp_path: Path) -> None:
    collection_root = tmp_path / "agent-owned"
    complete_runtime(tmp_path, collection_root)
    environment = {"ANSIBLE_COLLECTIONS_PATH": str(collection_root)}
    assert verify_deployment_ansible_runtime(tmp_path, environment) == PINS
    assert effective_ansible_collection_path(tmp_path, environment) == str(
        collection_root
    )


def test_system_collection_fallback_is_honored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system_root = tmp_path / "opt" / "ansible" / "collections"
    monkeypatch.setattr(adapter_module, "SYSTEM_ANSIBLE_COLLECTIONS", system_root)
    complete_runtime(tmp_path, system_root)
    assert verify_deployment_ansible_runtime(tmp_path, {}) == PINS


@pytest.mark.parametrize("missing", ["ansible.netcommon", "cisco.ios"])
def test_missing_required_collection_fails_closed(tmp_path: Path, missing: str) -> None:
    write_requirements(tmp_path)
    collection_root = tmp_path / ".ansible" / "collections"
    for name, version in PINS:
        if name != missing:
            install_manifest(collection_root, name, version)
    with pytest.raises(
        DeploymentRuntimeError,
        match=r"^deployment Ansible runtime prerequisites unavailable$",
    ):
        verify_deployment_ansible_runtime(tmp_path, {})


@pytest.mark.parametrize("wrong", ["ansible.netcommon", "cisco.ios"])
def test_wrong_required_collection_version_fails_closed(
    tmp_path: Path, wrong: str
) -> None:
    write_requirements(tmp_path)
    collection_root = tmp_path / ".ansible" / "collections"
    for name, version in PINS:
        install_manifest(collection_root, name, "0.0.1" if name == wrong else version)
    with pytest.raises(DeploymentRuntimeError):
        verify_deployment_ansible_runtime(tmp_path, {})


@pytest.mark.parametrize("contents", ["not-json", "{}", '{"collection_info": []}'])
def test_malformed_collection_metadata_fails_closed(
    tmp_path: Path, contents: str
) -> None:
    collection_root = tmp_path / ".ansible" / "collections"
    complete_runtime(tmp_path, collection_root)
    install_manifest(collection_root, "ansible.netcommon", "8.6.0", contents=contents)
    with pytest.raises(DeploymentRuntimeError):
        verify_deployment_ansible_runtime(tmp_path, {})


@pytest.mark.parametrize(
    "contents",
    [
        "not: [valid",
        "collections: []\n",
        "collections:\n  - name: ansible.netcommon\n    version: '>=8.6.0'\n",
        "collections:\n  - name: cisco.ios\n",
    ],
)
def test_malformed_or_nonexact_requirements_fail_closed(
    tmp_path: Path, contents: str
) -> None:
    write_requirements(tmp_path, contents)
    with pytest.raises(DeploymentRuntimeError):
        verify_deployment_ansible_runtime(tmp_path, {})


def test_missing_requirements_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(DeploymentRuntimeError):
        verify_deployment_ansible_runtime(tmp_path, {})


def test_duplicate_installed_collection_is_rejected_as_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_collections = tmp_path / ".ansible" / "collections"
    system_collections = tmp_path / "system-collections"
    monkeypatch.setattr(
        adapter_module, "SYSTEM_ANSIBLE_COLLECTIONS", system_collections
    )
    complete_runtime(tmp_path, repository_collections)
    install_manifest(system_collections, "ansible.netcommon", "8.6.0")
    with pytest.raises(DeploymentRuntimeError):
        verify_deployment_ansible_runtime(tmp_path, {})


def test_verification_has_no_network_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection_root = tmp_path / ".ansible" / "collections"
    complete_runtime(tmp_path, collection_root)

    def forbidden_socket(*_args, **_kwargs):
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    assert verify_deployment_ansible_runtime(tmp_path, {}) == PINS


@pytest.mark.parametrize(
    "configured",
    ["", "relative/path", f"/one{adapter_module.os.pathsep}/one"],
)
def test_unacceptable_explicit_search_path_fails_closed(
    tmp_path: Path, configured: str
) -> None:
    write_requirements(tmp_path)
    with pytest.raises(DeploymentRuntimeError):
        verify_deployment_ansible_runtime(
            tmp_path, {"ANSIBLE_COLLECTIONS_PATH": configured}
        )
