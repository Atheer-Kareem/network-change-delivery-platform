#!/usr/bin/env python3
"""Install a protected staging source bundle after merged-main review."""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import UUID

from network_change_delivery.protected_staging_install import install_source_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--controller-identity", required=True)
    parser.add_argument("--controller-url", required=True)
    parser.add_argument("--buildkite-pipeline-id", required=True, type=UUID)
    parser.add_argument("--netbox-url", required=True)
    parser.add_argument("--openbao-url", required=True)
    parser.add_argument("--cml-ca-pem-sha256", required=True)
    arguments = parser.parse_args()
    install_source_bundle(
        arguments.source,
        arguments.destination,
        arguments.commit,
        arguments.controller_identity,
        arguments.controller_url,
        arguments.buildkite_pipeline_id,
        arguments.netbox_url,
        arguments.openbao_url,
        arguments.cml_ca_pem_sha256,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
