"""Private filesystem boundary for continuous-observability runtime state."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class ObservabilityPrivatePathError(ValueError):
    """Raised when observability state crosses its reviewed private boundary."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def validate_observability_root(root: Path) -> None:
    """Reject relative, checkout, audit, and Oxidized-state roots."""
    if not root.is_absolute() or {"audit", "oxidized"}.intersection(root.parts):
        raise ObservabilityPrivatePathError("observability private root rejected")
    try:
        if root.resolve().is_relative_to(_project_root().resolve()):
            raise ObservabilityPrivatePathError("observability private root rejected")
    except OSError:
        raise ObservabilityPrivatePathError(
            "observability private root rejected"
        ) from None


def ensure_private_directory(path: Path) -> None:
    """Create or validate a current-user mode-0700 real directory."""
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as error:
        raise ObservabilityPrivatePathError(
            "observability private directory unavailable"
        ) from error
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ObservabilityPrivatePathError(
            "observability private directory unavailable"
        ) from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ObservabilityPrivatePathError("observability private directory rejected")


def ensure_private_tree(root: Path, *children: str) -> None:
    """Create one validated private root and direct child directories."""
    validate_observability_root(root)
    if not root.exists():
        root.mkdir(mode=0o700, parents=True)
    ensure_private_directory(root)
    for child in children:
        if not child or "/" in child or child in {".", ".."}:
            raise ObservabilityPrivatePathError(
                "observability private directory rejected"
            )
        ensure_private_directory(root / child)


def validate_private_file(
    path: Path, *, missing_ok: bool = False, maximum_bytes: int = 256 * 1024
) -> bytes | None:
    """Read one bounded, private, regular, single-link file."""
    try:
        metadata = path.lstat()
        content = path.read_bytes()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ObservabilityPrivatePathError(
            "observability private file unavailable"
        ) from None
    except OSError as error:
        raise ObservabilityPrivatePathError(
            "observability private file unavailable"
        ) from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or len(content) > maximum_bytes
    ):
        raise ObservabilityPrivatePathError("observability private file rejected")
    return content
