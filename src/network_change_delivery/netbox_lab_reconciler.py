"""Repository-independent lifecycle owner for the existing personal-lab NetBox."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

from network_change_delivery.inventory import InventoryError
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider

PROJECT = "netbox-docker"
EXPECTED_SERVICES = frozenset(
    {"netbox", "netbox-worker", "postgres", "redis", "redis-cache"}
)
NETBOX_IMAGE_ID = (
    "sha256:7ad3a287d38829c98799c4a03d874d3d309738d1f42987dfd8037ec0e80587ce"
)
NETBOX_IMAGE = "docker.io/netboxcommunity/netbox:v4.6.7-5.0.2"
API_URL = "http://127.0.0.1:8000"
DOCKER = "/usr/local/bin/docker"
DEFAULT_ROOT = Path("/Users/netdevops/.local/lib/ncdp/netbox-lab")
DEFAULT_TOKEN_PATH = Path("/Users/netdevops/.config/ncdp/netbox-lab/netbox-token")
COMMAND_TIMEOUT = 120


class NetBoxLabError(ValueError):
    """Bounded failure at the local NetBox lifecycle boundary."""


def _run(arguments: list[str], *, check: bool = True, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=check,
            timeout=timeout,
            shell=False,
            env={
                "HOME": str(Path.home()),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError):
        raise NetBoxLabError("NetBox lifecycle command failed") from None
    return result.stdout.strip()


def _private_contract(root: Path) -> dict[str, object]:
    contract_path = root / "contract.json"
    metadata = contract_path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise NetBoxLabError("NetBox lifecycle contract rejected")
    try:
        contract = json.loads(contract_path.read_bytes())
    except (OSError, ValueError):
        raise NetBoxLabError("NetBox lifecycle contract rejected") from None
    if not isinstance(contract, dict):
        raise NetBoxLabError("NetBox lifecycle contract rejected")
    return contract


def _private_token(path: Path) -> str:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            raise NetBoxLabError("NetBox lifecycle authority rejected")
        token = path.read_text().strip()
    except OSError:
        raise NetBoxLabError("NetBox lifecycle authority rejected") from None
    if not token:
        raise NetBoxLabError("NetBox lifecycle authority rejected")
    return token


def _verify_files(root: Path, contract: dict[str, object]) -> None:
    hashes = contract.get("files")
    if not isinstance(hashes, dict) or not hashes:
        raise NetBoxLabError("NetBox lifecycle file contract rejected")
    for relative, expected in hashes.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise NetBoxLabError("NetBox lifecycle file contract rejected")
        path = root / relative
        try:
            if path.is_symlink() or stat.S_IMODE(path.lstat().st_mode) & 0o077:
                raise NetBoxLabError("NetBox lifecycle file contract rejected")
            resolved = path.resolve(strict=True)
            resolved.relative_to(root.resolve(strict=True))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            raise NetBoxLabError("NetBox lifecycle file contract rejected") from None
        if digest != expected:
            raise NetBoxLabError("NetBox lifecycle file contract rejected")


def _json(command: list[str]) -> object:
    try:
        return json.loads(_run(command))
    except ValueError:
        raise NetBoxLabError("NetBox Docker inspection rejected") from None


def _json_lines(command: list[str]) -> list[dict[str, object]]:
    try:
        values = [json.loads(line) for line in _run(command).splitlines() if line]
    except ValueError:
        raise NetBoxLabError("NetBox Docker inspection rejected") from None
    if not all(isinstance(value, dict) for value in values):
        raise NetBoxLabError("NetBox Docker inspection rejected")
    return values


def _wait_docker() -> None:
    for _ in range(60):
        try:
            _run([DOCKER, "info", "--format", "{{.ServerVersion}}"], timeout=5)
            return
        except NetBoxLabError:
            time.sleep(2)
    raise NetBoxLabError("Docker unavailable for NetBox lifecycle")


def _verify_images(contract: dict[str, object]) -> None:
    images = contract.get("images")
    if not isinstance(images, dict) or images.get(NETBOX_IMAGE) != NETBOX_IMAGE_ID:
        raise NetBoxLabError("NetBox image contract rejected")
    for reference, expected_id in images.items():
        if not isinstance(reference, str) or not isinstance(expected_id, str):
            raise NetBoxLabError("NetBox image contract rejected")
        values = _json([DOCKER, "image", "inspect", reference])
        if (
            not isinstance(values, list)
            or len(values) != 1
            or values[0].get("Id") != expected_id
        ):
            raise NetBoxLabError("NetBox image contract rejected")


def _verify_volumes(contract: dict[str, object]) -> None:
    volumes = contract.get("volumes")
    if not isinstance(volumes, list) or not volumes:
        raise NetBoxLabError("NetBox volume contract rejected")
    for volume in volumes:
        if not isinstance(volume, str):
            raise NetBoxLabError("NetBox volume contract rejected")
        values = _json([DOCKER, "volume", "inspect", volume])
        if (
            not isinstance(values, list)
            or len(values) != 1
            or values[0].get("Name") != volume
            or values[0].get("Labels", {}).get("com.docker.compose.project") != PROJECT
        ):
            raise NetBoxLabError("NetBox volume contract rejected")


def _compose(root: Path, *arguments: str) -> list[str]:
    return [
        DOCKER,
        "compose",
        "-p",
        PROJECT,
        "--project-directory",
        str(root),
        "-f",
        str(root / "docker-compose.yml"),
        "-f",
        str(root / "docker-compose.override.yml"),
        *arguments,
    ]


def _verify_model(root: Path, contract: dict[str, object]) -> None:
    services = set(_run(_compose(root, "config", "--services")).splitlines())
    if services != EXPECTED_SERVICES:
        raise NetBoxLabError("NetBox Compose service contract rejected")
    images = sorted(_run(_compose(root, "config", "--images")).splitlines())
    if images != contract.get("service_images"):
        raise NetBoxLabError("NetBox Compose image contract rejected")


def _inspect_project(
    root: Path,
    contract: dict[str, object],
    *,
    allow_legacy_location: bool = False,
    allow_absent: bool = False,
) -> None:
    values = _json_lines(
        [
            DOCKER,
            "container",
            "ls",
            "--all",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "json",
        ]
    )
    if not values and allow_absent:
        return
    if len(values) != len(EXPECTED_SERVICES):
        raise NetBoxLabError("NetBox Compose population rejected")
    expected_names = contract.get("containers")
    actual_names = {value.get("Names") for value in values}
    if not isinstance(expected_names, list) or actual_names != set(expected_names):
        raise NetBoxLabError("NetBox Compose population rejected")
    images = contract.get("images")
    if not isinstance(images, dict):
        raise NetBoxLabError("NetBox image contract rejected")
    external_location = (
        str(root),
        f"{root / 'docker-compose.yml'},{root / 'docker-compose.override.yml'}",
    )
    allowed_locations = {external_location}
    if allow_legacy_location:
        allowed_locations.add(
            (contract.get("legacy_working_dir"), contract.get("legacy_config_files"))
        )
    for name in actual_names:
        inspected = _json([DOCKER, "inspect", str(name)])
        if not isinstance(inspected, list) or len(inspected) != 1:
            raise NetBoxLabError("NetBox container definition rejected")
        item = inspected[0]
        labels = item.get("Config", {}).get("Labels", {})
        if (
            labels.get("com.docker.compose.project") != PROJECT
            or (
                labels.get("com.docker.compose.project.working_dir"),
                labels.get("com.docker.compose.project.config_files"),
            )
            not in allowed_locations
            or item.get("HostConfig", {}).get("RestartPolicy", {}).get("Name")
            not in {"", "no"}
            or item.get("Image") != images.get(item.get("Config", {}).get("Image"))
        ):
            raise NetBoxLabError("NetBox container definition rejected")
        service = labels.get("com.docker.compose.service")
        if service not in EXPECTED_SERVICES:
            raise NetBoxLabError("NetBox container definition rejected")
        ports = item.get("HostConfig", {}).get("PortBindings", {}) or {}
        if service == "netbox":
            if ports != {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}:
                raise NetBoxLabError("NetBox publication contract rejected")
        elif ports:
            raise NetBoxLabError("NetBox publication contract rejected")


def _wait_health(token: str) -> None:
    provider = NetBoxProfileInventoryProvider(API_URL, token)
    for _ in range(90):
        try:
            provider.resolve_profiled_population()
            return
        except InventoryError:
            pass
        time.sleep(2)
    raise NetBoxLabError("NetBox authority health check failed")


def reconcile(root: Path = DEFAULT_ROOT) -> None:
    contract = _private_contract(root)
    token = _private_token(DEFAULT_TOKEN_PATH)
    _verify_files(root, contract)
    _wait_docker()
    _verify_images(contract)
    _verify_volumes(contract)
    _verify_model(root, contract)
    _inspect_project(root, contract, allow_legacy_location=True, allow_absent=True)
    _run(
        _compose(root, "up", "--detach", "--pull", "never", "--no-build"),
        timeout=COMMAND_TIMEOUT,
    )
    # Compose preserves compatible data-service containers during the one-time
    # move from the recorded legacy directory. Both locations are contract-bound;
    # a later necessary recreation converges labels to the external root.
    _inspect_project(root, contract, allow_legacy_location=True)
    _wait_health(token)


def main() -> int:
    if len(sys.argv) != 1:
        print("NetBox lifecycle arguments rejected", file=sys.stderr)
        return 2
    try:
        reconcile()
    except (NetBoxLabError, OSError, ValueError):
        print("NetBox lifecycle reconciliation failed", file=sys.stderr)
        return 2
    print("NetBox lifecycle reconciled: HEALTHY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
