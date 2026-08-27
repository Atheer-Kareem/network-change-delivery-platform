"""Shared private filesystem boundary for Oxidized runtime material."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class OxidizedPrivatePathError(ValueError):
    """Raised when an Oxidized private path crosses its reviewed boundary."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_oxidized_root(root: Path) -> None:
    """Reject checkout and named audit-namespace roots before any creation."""
    if (
        not root.is_absolute()
        or "audit" in root.parts
        or _is_within(root, _project_root())
    ):
        raise OxidizedPrivatePathError("Oxidized private root rejected")


def ensure_private_directory(path: Path) -> None:
    """Create or validate one current-user mode-0700 real directory."""
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as error:
        raise OxidizedPrivatePathError(
            "Oxidized private directory unavailable"
        ) from error
    try:
        metadata = path.lstat()
    except OSError as error:
        raise OxidizedPrivatePathError(
            "Oxidized private directory unavailable"
        ) from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise OxidizedPrivatePathError("Oxidized private directory rejected")


def validate_private_file(path: Path, *, missing_ok: bool = False) -> None:
    """Validate one current-user mode-0600 regular single-link file."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return
        raise OxidizedPrivatePathError("Oxidized private file unavailable") from None
    except OSError as error:
        raise OxidizedPrivatePathError("Oxidized private file unavailable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise OxidizedPrivatePathError("Oxidized private file rejected")
