#!/usr/bin/env python3
"""One-time personal-Mac deploy identity installation; never a Buildkite job."""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import re
import shlex
import stat
import tempfile
from pathlib import Path

from network_change_delivery.openbao_profiled_deploy_config import (
    DeployAgentCredentials,
    OpenBaoProfiledDeployConfigurator,
)

HOOK_DIRECTORY = Path.home() / ".config/buildkite/ncdp-lab/hooks/ncdp-deploy"
STATE_DIRECTORY = Path.home() / ".local/state/ncdp/openbao/buildkite-profiled-deploy"
NAMES = ("NCDP_OPENBAO_ROLE_ID", "NCDP_OPENBAO_SECRET_ID")
ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$")


def private_directory(path):
    info = path.lstat()
    if (
        not path.is_absolute()
        or path.resolve() != path
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or path.is_relative_to(Path(__file__).resolve().parents[2])
    ):
        raise ValueError("private directory rejected")


def private_file(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or not 0 < info.st_size <= 65536
    ):
        raise ValueError("private file rejected")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        return stream.read()


def atomic_private(path, content):
    descriptor, name = tempfile.mkstemp(prefix=".identity-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        private_file(path)
    finally:
        temporary.unlink(missing_ok=True)


def assignments(raw):
    values = {}
    for line in raw.decode().splitlines():
        match = ASSIGNMENT.fullmatch(line)
        if match:
            if match[1] in values:
                raise ValueError("duplicate setting rejected")
            values[match[1]] = match[2]
    return values


def read_credentials(path):
    values = assignments(private_file(path))
    if set(values) != set(NAMES):
        raise ValueError("dedicated credential file rejected")
    pair = [shlex.split(values[name]) for name in NAMES]
    if any(
        len(item) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", item[0])
        for item in pair
    ):
        raise ValueError("dedicated credential rejected")
    return DeployAgentCredentials(pair[0][0], pair[1][0])


def install(hooks, state, operator):
    private_directory(hooks)
    original = private_file(hooks / "profiled.env")
    inherited = hooks.parent.parent / "env/ncdp-deploy.env"
    values = assignments(private_file(inherited))
    values.update(assignments(original))
    required = {
        "NCDP_BUILDKITE_PIPELINE_ID",
        "NCDP_PROFILED_DELIVERY_STATE_ROOT",
        "NCDP_NETBOX_URL",
        "NCDP_NETBOX_TOKEN",
        "NCDP_OPENBAO_URL",
    }
    if not required.issubset(values) or any(not values[k] for k in required):
        raise ValueError("protected settings missing")
    if shlex.split(values["NCDP_OPENBAO_URL"]) != [operator.url]:
        raise ValueError("operator and protected OpenBao URL mismatch")
    if not state.is_absolute() or state.is_relative_to(
        Path(__file__).resolve().parents[2]
    ):
        raise ValueError("external state path required")
    state.mkdir(mode=0o700, exist_ok=True)
    private_directory(state)
    credentials_path = state / "approle.env"
    if credentials_path.is_symlink():
        raise ValueError("credential symlink rejected")
    source_line = f"source {shlex.quote(str(credentials_path))}"
    retained = []
    for line in original.decode().splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        match = ASSIGNMENT.fullmatch(stripped)
        if match and match[1] in NAMES:
            continue
        if stripped.startswith(("source ", ". ")):
            parts = shlex.split(stripped)
            if len(parts) != 2 or parts[1] not in {
                str(inherited),
                str(credentials_path),
            }:
                raise ValueError("unreviewed protected source")
            if parts[1] == str(credentials_path):
                continue
        retained.append(line)
    updated = ("".join(retained).rstrip("\n") + "\n" + source_line + "\n").encode()
    lock = os.open(
        state / ".install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(lock, "wb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("installation lock rejected")
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        operator.configure()
        pending = state / "issuance-pending"
        if not credentials_path.exists():
            if pending.exists():
                raise ValueError(
                    "previous issuance uncertain; operator review required"
                )
            atomic_private(
                pending, b"Issuance may have crossed; do not blindly reissue.\n"
            )
            pair = operator.issue()
            if any(
                not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", v)
                for v in (pair.role_id, pair.secret_id)
            ):
                raise ValueError("issued credential rejected")
            atomic_private(
                credentials_path,
                (
                    f"{NAMES[0]}={shlex.quote(pair.role_id)}\n{NAMES[1]}={shlex.quote(pair.secret_id)}\n"
                ).encode(),
            )
        pair = read_credentials(credentials_path)
        operator.verify(pair)
        if private_file(hooks / "profiled.env") != original:
            raise ValueError("protected settings changed during installation")
        atomic_private(hooks / "profiled.env", updated)
        pending.unlink(missing_ok=True)
        if private_file(hooks / "profiled.env") != updated:
            raise ValueError("protected integration verification failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook-directory", type=Path, default=HOOK_DIRECTORY)
    parser.add_argument("--state-directory", type=Path, default=STATE_DIRECTORY)
    args = parser.parse_args()
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    try:
        if any(
            os.environ.get(k)
            for k in ("BUILDKITE", "BUILDKITE_BUILD_ID", "BUILDKITE_JOB_ID")
        ):
            raise ValueError("operator-only installer")
        operator = OpenBaoProfiledDeployConfigurator(
            os.environ["NCDP_OPENBAO_URL"], os.environ["BAO_TOKEN"]
        )
        install(args.hook_directory, args.state_directory, operator)
    except Exception:
        print(
            "Deploy identity installation failed; private state retained, "
            "no automatic retry. No device access."
        )
        return 2
    print(
        "Dedicated deploy identity verified: persistent SecretID; unlimited logins; "
        "300-second / one-use tokens; exact reads 1/2."
    )
    print(
        "Dedicated credentials and profiled.env verified: agent-owned, mode 0600. "
        "No operator AppRole coupling; no agent restart required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
