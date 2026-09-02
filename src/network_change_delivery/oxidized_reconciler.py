"""Repository-independent one-shot persistent Oxidized reconciler."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from network_change_delivery.openbao_oxidized_bootstrap import OpenBaoOxidizedBootstrap
from network_change_delivery.oxidized_controller import EXPECTED_NODES
from network_change_delivery.oxidized_host_trust import (
    DEFAULT_TRUST_ROOT,
    validate_host_trust,
)
from network_change_delivery.oxidized_private_paths import validate_private_file
from network_change_delivery.oxidized_service import (
    API_URL,
    CONTAINER_NAME,
    OxidizedServiceError,
    docker_run_arguments,
    invalidate_readiness,
    publish_private_text,
    publish_readiness,
    validate_history_reservation,
    verify_container_definition,
)
from network_change_delivery.oxidized_source import (
    OxidizedSourcePublicationAmbiguousError,
    materialize_oxidized_source,
)
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider
from network_change_delivery.secrets import OpenBaoSecretProvider

STATE_ROOT = Path("/Users/netdevops/.local/state/ncdp/oxidized")
CONFIG_ROOT = Path("/Users/netdevops/.config/ncdp/oxidized")
DOCKER = "/usr/local/bin/docker"
COMMAND_TIMEOUT = 30


def _private(path: Path) -> str:
    validate_private_file(path)
    try:
        value = path.read_text().strip()
    except OSError as error:
        raise OxidizedServiceError("Oxidized private input unavailable") from error
    if not value:
        raise OxidizedServiceError("Oxidized private input unavailable")
    return value


def _docker(*arguments: str, check: bool = True) -> str:
    try:
        result = subprocess.run(
            [DOCKER, *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=check,
            timeout=COMMAND_TIMEOUT,
            shell=False,
            env={
                "HOME": str(Path.home()),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError):
        raise OxidizedServiceError("Oxidized Docker operation failed") from None
    return result.stdout.strip()


def _inspect() -> dict[str, object] | None:
    output = _docker("container", "inspect", CONTAINER_NAME, check=False)
    if output in {"", "[]"}:
        return None
    try:
        values = json.loads(output)
    except ValueError:
        raise OxidizedServiceError("Oxidized container inspection failed") from None
    if (
        not isinstance(values, list)
        or len(values) != 1
        or not isinstance(values[0], dict)
    ):
        raise OxidizedServiceError("Oxidized container inspection failed")
    return values[0]


def _remove_owned(inspect: dict[str, object], image_id: str) -> None:
    try:
        verify_container_definition(
            inspect,
            image_id,
            config_path=CONFIG_ROOT / "config",
            source_path=STATE_ROOT / "runtime" / "router.json",
            history_path=STATE_ROOT / "config-history.git",
            trust_path=DEFAULT_TRUST_ROOT,
            require_running=False,
        )
    except OxidizedServiceError:
        try:
            # One-time 10C-6 migration for the strict container created before
            # Docker Desktop bind ownership was observed on first Git write.
            verify_container_definition(
                inspect,
                image_id,
                config_path=CONFIG_ROOT / "config",
                source_path=STATE_ROOT / "runtime" / "router.json",
                history_path=STATE_ROOT / "config-history.git",
                trust_path=DEFAULT_TRUST_ROOT,
                require_git_config=False,
                require_running=False,
            )
        except OxidizedServiceError:
            # One-time, exact 10C-5 container migration.
            verify_container_definition(
                inspect,
                image_id,
                config_path=CONFIG_ROOT / "config",
                source_path=STATE_ROOT / "runtime" / "router.json",
                history_path=STATE_ROOT / "config-history.git",
                trust_path=None,
                require_git_config=False,
                require_running=False,
            )
    _docker("rm", "--force", CONTAINER_NAME)


def _wait_nodes() -> None:
    import httpx

    with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
        for _ in range(30):
            try:
                response = client.get(f"{API_URL}/nodes.json")
                data = (
                    response.json()
                    if response.status_code == 200 and len(response.content) < 65536
                    else None
                )
                if (
                    isinstance(data, list)
                    and {item.get("name") for item in data if isinstance(item, dict)}
                    == EXPECTED_NODES
                    and len(data) == 4
                    and all(
                        item.get("group") == "managed"
                        and isinstance(item.get("status"), str)
                        and (
                            item.get("last") is None
                            or isinstance(item.get("last"), dict)
                        )
                        for item in data
                    )
                ):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(1)
    raise OxidizedServiceError("Oxidized API readiness failed")


def reconcile() -> str:
    readiness = STATE_ROOT / "runtime" / "collection-ready.json"
    ambiguity = STATE_ROOT / "control" / "source-publication-ambiguous"
    force_reload = ambiguity.exists()
    invalidate_readiness(readiness)
    settings_path = CONFIG_ROOT / "authority.json"
    validate_private_file(settings_path)
    try:
        settings = json.loads(settings_path.read_bytes())
        netbox_url = settings["netbox_url"]
        openbao_url = settings["openbao_url"]
    except (OSError, ValueError, KeyError, TypeError):
        raise OxidizedServiceError("Oxidized authority settings rejected") from None
    if not isinstance(netbox_url, str) or not isinstance(openbao_url, str):
        raise OxidizedServiceError("Oxidized authority settings rejected")
    bootstrap = OpenBaoOxidizedBootstrap(openbao_url)
    source_login = bootstrap.issue_source_login(
        _private(STATE_ROOT / "operator" / "bootstrap-role-id"),
        _private(STATE_ROOT / "operator" / "bootstrap-secret-id"),
        _private(STATE_ROOT / "operator" / "role-id"),
    )
    try:
        result = materialize_oxidized_source(
            NetBoxProfileInventoryProvider(
                netbox_url, _private(CONFIG_ROOT / "netbox-token")
            ),
            OpenBaoSecretProvider(
                openbao_url, source_login.role_id, source_login.secret_id
            ),
            STATE_ROOT,
        )
    except OxidizedSourcePublicationAmbiguousError:
        publish_private_text(ambiguity, "AMBIGUOUS\n")
        raise
    image_id = _private(CONFIG_ROOT / "image-id")
    validate_private_file(CONFIG_ROOT / "gitconfig")
    history = STATE_ROOT / "config-history.git"
    validate_history_reservation(history)
    validate_host_trust(DEFAULT_TRUST_ROOT)
    inspect = _inspect()
    restart = (
        result.changed
        or force_reload
        or inspect is None
        or inspect.get("State", {}).get("Running") is not True
    )
    if inspect is not None and not restart:
        try:
            container_id = verify_container_definition(
                inspect,
                image_id,
                config_path=CONFIG_ROOT / "config",
                source_path=result.path,
                history_path=history,
                trust_path=DEFAULT_TRUST_ROOT,
            )
        except OxidizedServiceError:
            try:
                verify_container_definition(
                    inspect,
                    image_id,
                    config_path=CONFIG_ROOT / "config",
                    source_path=result.path,
                    history_path=history,
                    trust_path=DEFAULT_TRUST_ROOT,
                    require_git_config=False,
                )
            except OxidizedServiceError:
                verify_container_definition(
                    inspect,
                    image_id,
                    config_path=CONFIG_ROOT / "config",
                    source_path=result.path,
                    history_path=history,
                    trust_path=None,
                    require_git_config=False,
                )
            restart = True
    if restart:
        if inspect is not None:
            _remove_owned(inspect, image_id)
        arguments = docker_run_arguments(
            image_id=image_id,
            config_path=CONFIG_ROOT / "config",
            source_path=result.path,
            history_path=history,
            trust_path=DEFAULT_TRUST_ROOT,
        )
        _docker(*arguments[1:])
        inspect = _inspect()
        if inspect is None:
            raise OxidizedServiceError("Oxidized container unavailable")
        container_id = verify_container_definition(
            inspect,
            image_id,
            config_path=CONFIG_ROOT / "config",
            source_path=result.path,
            history_path=history,
            trust_path=DEFAULT_TRUST_ROOT,
        )
    _wait_nodes()
    publish_readiness(readiness, container_id, trust_path=DEFAULT_TRUST_ROOT)
    ambiguity.unlink(missing_ok=True)
    return container_id


def main() -> int:
    if len(sys.argv) != 1:
        print("Oxidized service arguments rejected", file=sys.stderr)
        return 2
    try:
        reconcile()
    except (OxidizedServiceError, ValueError, OSError):
        print("Oxidized service reconciliation failed", file=sys.stderr)
        return 2
    print("Oxidized service reconciled: READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
