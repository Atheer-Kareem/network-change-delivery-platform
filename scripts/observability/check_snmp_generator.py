#!/usr/bin/env python3
"""Regenerate and compare the reviewed SNMP exporter module."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from network_change_delivery.snmp_mib import validate_generated_module

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "infrastructure/observability/snmp/generator.yml"
GENERATED = ROOT / "infrastructure/observability/snmp/snmp-modules.yml"
GENERATOR_IMAGE = (
    "prom/snmp-generator:v0.30.1@"
    "sha256:7302a6703ec9eebdc901b7f1f876121ccaea636121fcb86e8211f6becc53fb43"
)
NET_SNMP_COMMIT = "c4d46f9f7b5b32bf1d6b61d09bdabaae4ff3cd7a"
MIBS = {
    "IF-MIB.txt": "a41d2d0414bd6e1b3249257d0d035ea11554624c525b830f6910195b72b0c297",
    "IANAifType-MIB.txt": (
        "1bb1a2e5938abfd21ed019ff0c9cec71d2e2387b266737a37fe9516307b7afd8"
    ),
    "SNMPv2-CONF.txt": (
        "b3e90ba682e10c76f6de90e65a0013143f0ec531b0ed546b2b8aa5ad5c0001eb"
    ),
    "SNMPv2-MIB.txt": (
        "b4f8ef130f580b86d2b6bc890564e46100785f589431df76954e878a7b166e11"
    ),
    "SNMPv2-SMI.txt": (
        "ece2355fc8b6140af702f86d77bd3f7398d80375fc6278c3e30ff3a31b53e0b7"
    ),
    "SNMPv2-TC.txt": "c1379575e6a0ad25b2d7da68294153c1fd79750827376f2aa6323d072d73f0b8",
}


def download_mibs(directory: Path) -> None:
    """Fetch the exact standard MIB inputs and verify every byte."""
    directory.mkdir(mode=0o700)
    with httpx.Client(follow_redirects=False, timeout=20, trust_env=False) as client:
        for name, expected in MIBS.items():
            url = (
                "https://raw.githubusercontent.com/net-snmp/net-snmp/"
                f"{NET_SNMP_COMMIT}/mibs/{name}"
            )
            response = client.get(url)
            response.raise_for_status()
            content = response.content
            if hashlib.sha256(content).hexdigest() != expected:
                raise RuntimeError(f"standard MIB digest rejected: {name}")
            (directory / name).write_bytes(content)


def generate(destination: Path) -> bytes:
    """Run the exact upstream generator under explicit AMD64 emulation."""
    shutil.copyfile(SOURCE, destination / "generator.yml")
    download_mibs(destination / "mibs")
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--pull",
            "missing",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{destination}:/opt",
            GENERATOR_IMAGE,
            "--fail-on-parse-errors",
            "generate",
        ],
        check=True,
    )
    return (destination / "snmp.yml").read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write", action="store_true", help="replace the committed generated output"
    )
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ncdp-snmp-generator-") as temporary:
        content = generate(Path(temporary))
    validate_generated_module(content)
    if arguments.write:
        GENERATED.write_bytes(content)
        print(f"wrote {GENERATED.relative_to(ROOT)}")
        return 0
    if not GENERATED.is_file() or GENERATED.read_bytes() != content:
        print("generated SNMP module differs; run this command with --write")
        return 1
    print("generated SNMP module is reproducible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
