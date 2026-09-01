#!/usr/bin/env python3
"""One-shot continuity-gated initialization of all four real LIVE D0 chains."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from network_change_delivery.audit import canonical_json_bytes
from network_change_delivery.managed_state_live import (
    LiveManagedStateError,
    collect_live_managed_state,
    initialize_live_d0_store,
)
from network_change_delivery.managed_state_store import ManagedStateStoreError
from network_change_delivery.openbao_profiled_config import (
    OpenBaoProfiledDeviceConfigurator,
)
from network_change_delivery.secrets import OpenBaoSecretProvider, SecretError


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store-root",
        type=Path,
        default=os.environ.get("NCDP_MANAGED_STATE_STORE_ROOT"),
        required="NCDP_MANAGED_STATE_STORE_ROOT" not in os.environ,
    )
    parser.add_argument("--source-git-commit", required=True)
    parser.add_argument("--result", type=Path)
    return parser.parse_args()


def _publish_result(path: Path, content: bytes, checkout: Path) -> None:
    if (
        not path.is_absolute()
        or path.exists()
        or path.is_symlink()
        or path.resolve().is_relative_to(checkout.resolve())
    ):
        raise LiveManagedStateError("initial-adoption result path is unsafe")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    os.umask(0o077)
    arguments = _arguments()
    checkout = Path(__file__).resolve().parents[2]
    issuer = OpenBaoProfiledDeviceConfigurator.from_environment()
    issued_accessors: set[str] = set()
    retired_sessions = 0

    def fresh_pass():
        nonlocal retired_sessions
        session = issuer.issue_bounded_session()
        if session.secret_id_accessor in issued_accessors:
            issuer.retire_bounded_session(session)
            retired_sessions += 1
            raise LiveManagedStateError("OpenBao returned a reused AppRole SecretID")
        issued_accessors.add(session.secret_id_accessor)
        try:
            provider = OpenBaoSecretProvider(
                url=os.environ.get("NCDP_OPENBAO_URL"),
                role_id=session.role_id,
                secret_id=session.secret_id,
            )
            return collect_live_managed_state(provider)
        finally:
            issuer.retire_bounded_session(session)
            retired_sessions += 1

    try:
        result = initialize_live_d0_store(
            final_root=arguments.store_root,
            checkout=checkout,
            source_git_commit=arguments.source_git_commit,
            collect_first=fresh_pass,
            collect_second=fresh_pass,
        )
        if len(issued_accessors) != 2 or retired_sessions != 2:
            raise LiveManagedStateError(
                "two distinct AppRole sessions were not retired"
            )
        encoded = canonical_json_bytes(result.model_dump(mode="json"))
        if arguments.result is not None:
            _publish_result(arguments.result, encoded, checkout)
        print(encoded.decode())
    except (
        LiveManagedStateError,
        ManagedStateStoreError,
        SecretError,
        ValueError,
    ) as error:
        print(f"LIVE D0 initialization failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
