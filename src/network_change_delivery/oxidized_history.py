"""Metadata-only reader for the private Oxidized Git chronology."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from network_change_delivery.configuration_observation import OxidizedRevision
from network_change_delivery.oxidized_private_paths import (
    OxidizedPrivatePathError,
    validate_oxidized_root,
)

OXIDIZED_REPOSITORY_IDENTITY = "oxidized:ncdp-lab-actual-state"
OXIDIZED_GIT_AUTHOR = "NCDP Oxidized"
OXIDIZED_GIT_EMAIL = "oxidized@ncdp.local"
OXIDIZED_GROUP = "managed"
OXIDIZED_HISTORY_DIRECTORY = "config-history.git"
GIT_EXECUTABLE = "/usr/bin/git"
GIT_TIMEOUT_SECONDS = 5
GIT_MAX_OUTPUT_BYTES = 4096

_NODE_PATTERN = re.compile(r"^netbox-device-[1-9][0-9]*$")
_OID_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class OxidizedHistoryError(ValueError):
    """Bounded failure that never exposes configuration or Git stderr."""


def canonical_config_path(node_name: str, group: str = OXIDIZED_GROUP) -> str:
    """Build the one reviewed group/node chronology path."""
    if group != OXIDIZED_GROUP or not _NODE_PATTERN.fullmatch(node_name):
        raise OxidizedHistoryError("Oxidized history identity rejected")
    return f"{group}/{node_name}"


class OxidizedHistoryRepository:
    """Validate and read path-scoped metadata from one private bare repository."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
        }

    def _git(self, *arguments: str) -> bytes:
        try:
            result = subprocess.run(
                [GIT_EXECUTABLE, f"--git-dir={self._path}", *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
                shell=False,
                timeout=GIT_TIMEOUT_SECONDS,
                env=self._environment(),
            )
        except (OSError, subprocess.SubprocessError):
            raise OxidizedHistoryError("Oxidized history unavailable") from None
        if len(result.stdout) > GIT_MAX_OUTPUT_BYTES:
            raise OxidizedHistoryError("Oxidized history unavailable")
        return result.stdout

    def _has_local_remote(self) -> bool:
        try:
            result = subprocess.run(
                [
                    GIT_EXECUTABLE,
                    f"--git-dir={self._path}",
                    "config",
                    "--local",
                    "--get-regexp",
                    r"^remote\..*\.url$",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=GIT_TIMEOUT_SECONDS,
                env=self._environment(),
            )
        except (OSError, subprocess.SubprocessError):
            raise OxidizedHistoryError("Oxidized history unavailable") from None
        if result.returncode not in {0, 1}:
            raise OxidizedHistoryError("Oxidized history unavailable")
        return result.returncode == 0

    def _validate_repository(self) -> None:
        try:
            validate_oxidized_root(self._path)
            metadata = self._path.lstat()
        except (OSError, OxidizedPrivatePathError):
            raise OxidizedHistoryError("Oxidized history unavailable") from None
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise OxidizedHistoryError("Oxidized history repository rejected")
        if self._git("rev-parse", "--is-bare-repository").strip() != b"true":
            raise OxidizedHistoryError("Oxidized history repository rejected")
        object_format = self._git("rev-parse", "--show-object-format").strip()
        if object_format not in {b"sha1", b"sha256"}:
            raise OxidizedHistoryError("Oxidized history repository rejected")
        if (
            self._has_local_remote()
            or self._git(
                "for-each-ref", "--count=1", "--format=%(refname)", "refs/replace"
            ).strip()
        ):
            raise OxidizedHistoryError("Oxidized history repository rejected")
        alternates = self._path / "objects" / "info" / "alternates"
        if alternates.exists() or alternates.is_symlink():
            raise OxidizedHistoryError("Oxidized history repository rejected")
        objects = self._path / "objects"
        try:
            objects_metadata = objects.lstat()
            local_objects = objects.resolve().is_relative_to(self._path.resolve())
        except OSError:
            raise OxidizedHistoryError("Oxidized history repository rejected") from None
        if (
            stat.S_ISLNK(objects_metadata.st_mode)
            or not stat.S_ISDIR(objects_metadata.st_mode)
            or not local_objects
        ):
            raise OxidizedHistoryError("Oxidized history repository rejected")
        head = self._git("rev-parse", "--verify", "HEAD^{commit}").strip().decode()
        if not _OID_PATTERN.fullmatch(head):
            raise OxidizedHistoryError("Oxidized history unavailable")

    def latest_revision(
        self, node_name: str, group: str = OXIDIZED_GROUP
    ) -> OxidizedRevision:
        """Return the newest commit affecting one path, without reading its blob."""
        path = canonical_config_path(node_name, group)
        self._validate_repository()
        log = self._git(
            "log",
            "-1",
            "--no-show-signature",
            "--format=%H%x00%cI",
            "--",
            path,
        )
        fields = log.rstrip(b"\n").split(b"\x00")
        if len(fields) != 2:
            raise OxidizedHistoryError("Oxidized history unavailable")
        try:
            commit = fields[0].decode("ascii")
            parsed_timestamp = datetime.fromisoformat(fields[1].decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            raise OxidizedHistoryError("Oxidized history unavailable") from None
        if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
            raise OxidizedHistoryError("Oxidized history unavailable")
        timestamp = parsed_timestamp.astimezone(UTC)
        tree = self._git("ls-tree", "-z", commit, "--", path)
        entries = [entry for entry in tree.split(b"\x00") if entry]
        if len(entries) != 1:
            raise OxidizedHistoryError("Oxidized history unavailable")
        try:
            metadata, returned_path = entries[0].split(b"\t", maxsplit=1)
            mode, object_type, blob = metadata.decode("ascii").split(" ")
            exact_path = returned_path.decode("ascii")
        except (UnicodeDecodeError, ValueError):
            raise OxidizedHistoryError("Oxidized history unavailable") from None
        if (
            mode != "100644"
            or object_type != "blob"
            or exact_path != path
            or not _OID_PATTERN.fullmatch(commit)
            or not _OID_PATTERN.fullmatch(blob)
            or len(commit) != len(blob)
        ):
            raise OxidizedHistoryError("Oxidized history unavailable")
        try:
            return OxidizedRevision(
                commit=commit,
                config_path=path,
                blob=blob,
                collected_at=timestamp,
            )
        except ValidationError:
            raise OxidizedHistoryError("Oxidized history unavailable") from None
