#!/usr/bin/env python3
"""Operator-only bounded session preparation; never part of a Buildkite job."""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import pwd
import re
import shlex
import stat
import tempfile
from pathlib import Path

from network_change_delivery.openbao_profiled_config import (
    OpenBaoProfiledDeviceConfigurator,
    ProfiledOpenBaoSession,
)

DEFAULT_DIRECTORY = Path.home() / ".config/buildkite/ncdp-lab/hooks/ncdp-deploy"
ROLE = "NCDP_OPENBAO_ROLE_ID"
SECRET = "NCDP_OPENBAO_SECRET_ID"
REQUIRED = {
    ROLE,
    SECRET,
    "NCDP_BUILDKITE_PIPELINE_ID",
    "NCDP_NETBOX_URL",
    "NCDP_NETBOX_TOKEN",
    "NCDP_OPENBAO_URL",
    "NCDP_PROFILED_DELIVERY_STATE_ROOT",
}
ASSIGNMENT = re.compile(r"^(?:export[ \t]+)?([A-Z][A-Z0-9_]*)=(.*)$")
ACCESSOR = "profiled-session.accessor"


def private_file(path: Path) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("protected file rejected")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or not 0 < info.st_size <= 65536
        ):
            raise ValueError("protected file rejected")
        return stream.read()


def settings(directory: Path, source: bytes) -> dict[str, str]:
    """Inspect assignments, never execute protected shell or expand credentials."""
    values = {}
    for line in source.decode().splitlines():
        match = ASSIGNMENT.fullmatch(line)
        if match:
            name, value = match.groups()
            if name in values:
                raise ValueError("duplicate protected assignment")
            values[name] = value
    # Retain the existing reviewed external NetBox/settings source convention.
    inherited = {}
    allowed = directory.parent.parent / "env/ncdp-deploy.env"
    for line in source.decode().splitlines():
        if line.startswith(("source ", ". ")):
            if shlex.split(line) not in (["source", str(allowed)], [".", str(allowed)]):
                raise ValueError("unreviewed environment source")
            for item in private_file(allowed).decode().splitlines():
                match = ASSIGNMENT.fullmatch(item)
                if match:
                    inherited[match[1]] = match[2]
    inherited.update(values)
    if not REQUIRED.issubset(inherited) or ROLE not in values or SECRET not in values:
        raise ValueError("required protected names missing")
    return inherited


def replace_session(source: bytes, session: ProfiledOpenBaoSession | None) -> bytes:
    replacements = {
        ROLE: session.role_id if session else "",
        SECRET: session.secret_id if session else "",
    }
    lines = source.decode().splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = ASSIGNMENT.fullmatch(line.rstrip("\r\n"))
        if match and match[1] in replacements:
            ending = (
                "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            )
            prefix = "export " if line.startswith("export ") else ""
            lines[index] = (
                f"{prefix}{match[1]}={shlex.quote(replacements[match[1]])}{ending}"
            )
    return "".join(lines).encode()


def atomic_private(path: Path, content: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".session-tmp-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        private_file(path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(directory: Path, operator, url: str, *, retire_only: bool = False):
    info = directory.lstat()
    if (
        not directory.is_absolute()
        or directory.resolve() != directory
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or directory.is_relative_to(Path(__file__).resolve().parents[2])
    ):
        raise ValueError("private agent directory rejected")
    lock = os.open(
        directory / ".session-preparation.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(lock, "wb") as lock_file:
        lock_info = os.fstat(lock_file.fileno())
        if (
            lock_info.st_uid != os.getuid()
            or not stat.S_ISREG(lock_info.st_mode)
            or stat.S_IMODE(lock_info.st_mode) != 0o600
            or lock_info.st_nlink != 1
        ):
            raise ValueError("session lock rejected")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        protected = directory / "profiled.env"
        original = private_file(protected)
        values = settings(directory, original)
        if shlex.split(values["NCDP_OPENBAO_URL"]) != [url]:
            raise ValueError("operator OpenBao URL differs from protected settings")
        accessor_path = directory / ACCESSOR
        prior = None
        if accessor_path.exists() or accessor_path.is_symlink():
            prior = private_file(accessor_path).decode().strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", prior):
                raise ValueError("recorded accessor rejected")
        if retire_only and prior is None:
            raise ValueError("no known issued session to retire")
        if prior:
            # Unknown sessions are never enumerated or retired. No mutation retry.
            operator.retire_bounded_session(ProfiledOpenBaoSession("", "", prior))
            accessor_path.unlink()
        if retire_only:
            updated = replace_session(original, None)
        else:
            session = operator.issue_bounded_session()
            if not all(
                re.fullmatch(r"[A-Za-z0-9_-]{1,512}", item)
                for item in (
                    session.role_id,
                    session.secret_id,
                    session.secret_id_accessor,
                )
            ):
                raise ValueError("bounded session rejected")
            # Journal before env installation: failure retains the accessor for
            # explicit retirement. A crash before journaling is bounded by TTL.
            atomic_private(accessor_path, (session.secret_id_accessor + "\n").encode())
            updated = replace_session(original, session)
        if private_file(protected) != original:
            raise ValueError("protected environment changed during preparation")
        atomic_private(protected, updated)
        if private_file(protected) != updated:
            raise ValueError("protected publication did not verify")
        settings(directory, updated)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "retire"))
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument(
        "--confirm-idle",
        action="store_true",
        required=True,
        help="operator confirms no running/pending main build needs this session",
    )
    arguments = parser.parse_args()
    logging.disable(logging.CRITICAL)
    os.umask(0o077)
    try:
        if (
            os.environ.get("BUILDKITE")
            or os.environ.get("BUILDKITE_BUILD_ID")
            or os.environ.get("BUILDKITE_JOB_ID")
        ):
            raise ValueError("preparation cannot run inside Buildkite")
        operator = OpenBaoProfiledDeviceConfigurator.from_environment()
        prepare(
            arguments.directory,
            operator,
            os.environ["NCDP_OPENBAO_URL"],
            retire_only=arguments.action == "retire",
        )
    except Exception:
        print(
            "Bounded session preparation/retirement failed; no automatic retry. "
            "Retain private session state for operator review. No device access."
        )
        return 2
    info = (arguments.directory / "profiled.env").stat()
    print(
        f"Protected environment verified: owner={pwd.getpwuid(info.st_uid).pw_name}; "
        "mode=0600"
    )
    print("Required names: " + ", ".join(sorted(REQUIRED)))
    print(
        "Fresh bounded session installed (30 minutes / 10 uses)."
        if arguments.action == "prepare"
        else "Known bounded session retired; agent session entries cleared."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
