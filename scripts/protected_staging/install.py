#!/usr/bin/env python3
"""Install a protected staging source bundle after merged-main review."""

from __future__ import annotations

import argparse
from pathlib import Path

from network_change_delivery.protected_staging_install import install_source_bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--controller-identity", required=True)
    parser.add_argument("--controller-url", required=True)
    arguments = parser.parse_args()
    install_source_bundle(
        arguments.source,
        arguments.destination,
        arguments.commit,
        arguments.controller_identity,
        arguments.controller_url,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
