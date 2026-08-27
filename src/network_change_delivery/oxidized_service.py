"""Persistent Oxidized service contracts and fail-closed reconciliation helpers."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from network_change_delivery.oxidized_controller import EXPECTED_NODES, CollectionReady
from network_change_delivery.oxidized_history import (
    OXIDIZED_GIT_AUTHOR,
    OXIDIZED_GIT_EMAIL,
)
from network_change_delivery.oxidized_private_paths import (
    ensure_private_directory,
    validate_private_file,
)

SERVICE_LABEL = "com.ncdp.oxidized"
CONTAINER_NAME = "ncdp-oxidized"
OWNERSHIP_LABEL = "com.ncdp.service=oxidized"
API_URL = "http://127.0.0.1:8888"
READINESS_TTL = timedelta(minutes=15)
ENSURE_INTERVAL_SECONDS = 300
DOCKER_TIMEOUT_SECONDS = 30


class OxidizedServiceError(ValueError):
    """Bounded local service failure."""


def render_oxidized_config() -> str:
    return f"""---
interval: 0
threads: 1
retries: 0
timeout: 20
timelimit: 60
use_syslog: false
next_adds_job: true
rest: 0.0.0.0:8888
source:
  default: jsonfile
  jsonfile:
    file: /run/ncdp/router.json
    map:
      name: name
      ip: ip
      model: model
      group: group
      username: username
      password: password
    vars_map:
      ssh_port: ssh_port
output:
  default: git
  git:
    single_repo: true
    user: {OXIDIZED_GIT_AUTHOR}
    email: {OXIDIZED_GIT_EMAIL}
    repo: /var/lib/ncdp/config-history.git
    type_as_directory: false
"""


def publish_private_text(path: Path, value: str, *, mode: int = 0o600) -> None:
    ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        os.write(descriptor, value.encode())
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        validate_private_file(path)
    except OSError as error:
        raise OxidizedServiceError("Oxidized private publication failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def invalidate_readiness(path: Path) -> None:
    with suppress(FileNotFoundError):
        path.unlink()


def publish_readiness(
    path: Path, container_id: str, *, now: datetime | None = None
) -> CollectionReady:
    refreshed = now or datetime.now(UTC)
    marker = CollectionReady(
        refreshed_at=refreshed,
        expires_at=refreshed + READINESS_TTL,
        nodes=tuple(sorted(EXPECTED_NODES)),
        container_id=container_id,
    )
    publish_private_text(path, marker.model_dump_json() + "\n")
    return marker


def validate_history_reservation(path: Path) -> None:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise OxidizedServiceError("Oxidized history reservation rejected")
    environment = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }
    try:
        bare = subprocess.run(
            ["/usr/bin/git", f"--git-dir={path}", "rev-parse", "--is-bare-repository"],
            capture_output=True,
            check=True,
            timeout=5,
            env=environment,
        )
        remote = subprocess.run(
            [
                "/usr/bin/git",
                f"--git-dir={path}",
                "config",
                "--local",
                "--name-only",
                "--get-regexp",
                r"^remote\.",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        raise OxidizedServiceError("Oxidized history reservation rejected") from None
    if (
        bare.stdout.strip() != b"true"
        or remote.returncode != 1
        or (path / "objects/info/alternates").exists()
        or (path / "refs/replace").exists()
    ):
        raise OxidizedServiceError("Oxidized history reservation rejected")


def docker_run_arguments(
    *,
    image_id: str,
    config_path: Path,
    source_path: Path,
    history_path: Path,
    uid: int | None = None,
    gid: int | None = None,
) -> list[str]:
    effective_uid = uid if uid is not None else os.getuid()
    effective_gid = gid if gid is not None else os.getgid()
    user = f"{effective_uid}:{effective_gid}"
    if not image_id.startswith("sha256:") or len(image_id) != 71:
        raise OxidizedServiceError("Oxidized image identity rejected")
    return [
        "/usr/local/bin/docker",
        "run",
        "--detach",
        "--pull",
        "never",
        "--name",
        CONTAINER_NAME,
        "--label",
        OWNERSHIP_LABEL,
        "--restart",
        "no",
        "--user",
        user,
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--publish",
        "127.0.0.1:8888:8888",
        "--env",
        "HOME=/run/ncdp/home",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size=16m,uid={os.getuid()},gid={os.getgid()}",
        "--tmpfs",
        f"/run/ncdp:rw,noexec,nosuid,nodev,size=32m,mode=0700,uid={os.getuid()},gid={os.getgid()}",
        "--mount",
        f"type=bind,source={config_path},target=/run/ncdp/config,readonly",
        "--mount",
        f"type=bind,source={source_path},target=/run/ncdp/router.json,readonly",
        "--mount",
        f"type=bind,source={history_path},target=/var/lib/ncdp/config-history.git",
        image_id,
        "--config",
        "/run/ncdp/config",
    ]


def verify_container_definition(
    inspect: dict[str, object], image_id: str, *, require_running: bool = True
) -> str:
    try:
        config = inspect["Config"]
        host = inspect["HostConfig"]
        state = inspect["State"]
        identifier = inspect["Id"]
        labels = config["Labels"]
    except (KeyError, TypeError):
        raise OxidizedServiceError("Oxidized container definition rejected") from None
    environments = config.get("Env", [])
    bindings = host.get("PortBindings", {}).get("8888/tcp", [])
    if (
        labels.get("com.ncdp.service") != "oxidized"
        or config.get("Image") != image_id
        or config.get("User") != f"{os.getuid()}:{os.getgid()}"
        or host.get("Privileged")
        or host.get("ReadonlyRootfs") is not True
        or host.get("NetworkMode") == "host"
        or "ALL" not in (host.get("CapDrop") or [])
        or "no-new-privileges" not in (host.get("SecurityOpt") or [])
        or host.get("RestartPolicy", {}).get("Name") not in {"", "no"}
        or bindings != [{"HostIp": "127.0.0.1", "HostPort": "8888"}]
        or not isinstance(environments, list)
        or any(
            any(
                secret in item.upper()
                for secret in ("TOKEN", "SECRET", "PASSWORD", "ROLE_ID")
            )
            for item in environments
            if isinstance(item, str)
        )
        or (require_running and state.get("Running") is not True)
        or not isinstance(identifier, str)
        or len(identifier) != 64
    ):
        raise OxidizedServiceError("Oxidized container definition rejected")
    return identifier
