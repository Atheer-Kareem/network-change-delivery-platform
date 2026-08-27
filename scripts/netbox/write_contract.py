#!/usr/bin/env python3
"""Write a secret-free contract for one discovered existing NetBox stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

PROJECT = "netbox-docker"
EXPECTED_CONTAINERS = {
    "netbox-docker-netbox-1",
    "netbox-docker-netbox-worker-1",
    "netbox-docker-postgres-1",
    "netbox-docker-redis-1",
    "netbox-docker-redis-cache-1",
}
EXPECTED_VOLUMES = {
    "netbox-docker_netbox-media-files",
    "netbox-docker_netbox-postgres",
    "netbox-docker_netbox-redis-cache-data",
    "netbox-docker_netbox-redis-data",
    "netbox-docker_netbox-reports-files",
    "netbox-docker_netbox-scripts-files",
}


def run(*arguments: str) -> str:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    target = args.target.resolve(strict=True)
    containers = set(
        run(
            "/usr/local/bin/docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "{{.Names}}",
        ).splitlines()
    )
    volumes = set(
        run(
            "/usr/local/bin/docker",
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "{{.Name}}",
        ).splitlines()
    )
    if containers != EXPECTED_CONTAINERS or volumes != EXPECTED_VOLUMES:
        raise SystemExit("NetBox discovered identity rejected")
    images: dict[str, str] = {}
    service_images: list[str] = []
    working_directories: set[str] = set()
    config_files: set[str] = set()
    for name in sorted(containers):
        values = json.loads(run("/usr/local/bin/docker", "inspect", name))
        item = values[0]
        labels = item["Config"]["Labels"]
        if (
            labels.get("com.docker.compose.project") != PROJECT
            or item["State"]["Running"]
            or item["HostConfig"]["RestartPolicy"]["Name"] not in {"", "no"}
        ):
            raise SystemExit("NetBox discovered container rejected")
        images[item["Config"]["Image"]] = item["Image"]
        service_images.append(item["Config"]["Image"])
        working_directories.add(labels["com.docker.compose.project.working_dir"])
        config_files.add(labels["com.docker.compose.project.config_files"])
    if len(working_directories) != 1 or len(config_files) != 1:
        raise SystemExit("NetBox discovered Compose location rejected")
    files: dict[str, str] = {}
    for path in sorted(target.rglob("*")):
        if path.is_file() and path.name != "contract.json":
            relative = str(path.relative_to(target))
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    contract = {
        "schema_version": "1",
        "project": PROJECT,
        "source_config_hashes": {
            "docker-compose.yml": hashlib.sha256(
                (source / "docker-compose.yml").read_bytes()
            ).hexdigest(),
            "docker-compose.override.yml": hashlib.sha256(
                (source / "docker-compose.override.yml").read_bytes()
            ).hexdigest(),
        },
        "containers": sorted(containers),
        "volumes": sorted(volumes),
        "images": dict(sorted(images.items())),
        "service_images": sorted(service_images),
        "legacy_working_dir": working_directories.pop(),
        "legacy_config_files": config_files.pop(),
        "files": files,
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=".contract.", dir=target)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, (json.dumps(contract, sort_keys=True) + "\n").encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    Path(temporary_name).replace(target / "contract.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
