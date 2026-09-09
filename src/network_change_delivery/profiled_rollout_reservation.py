"""Local process-held stable-device reservations; no cross-host/atomicity claim."""

import fcntl
import os
import stat
from contextlib import contextmanager, suppress
from pathlib import Path

from pydantic import TypeAdapter

from network_change_delivery.profiled_rollout import MAX_MEMBERS, DeviceIdentity

DIRECTORY = "profiled-rollout-reservations"
CHECKOUT = Path(__file__).resolve().parents[2]


def _private_directory(info):
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("rollout reservation directory rejected")


@contextmanager
def reserve_rollout_devices(state_root: Path, devices: tuple[str, ...]):
    """Reserve all stable devices, including compliant members, or none.

    Caller must verify human authorization before entering. Never hold across a
    human pause. Acquire in lexical stable-identity order, nonblocking. Empty
    files remain after release; kernel locks, not files, represent ownership.
    Future integration must also cover the single-target protected write path.
    """
    if (
        not isinstance(devices, tuple)
        or not 0 < len(devices) <= MAX_MEMBERS
        or any(not isinstance(d, str) or len(d) > 100 for d in devices)
    ):
        raise ValueError("rollout reservation identities rejected")
    devices = TypeAdapter(tuple[DeviceIdentity, ...]).validate_python(devices)
    if len(set(devices)) != len(devices):
        raise ValueError("duplicate rollout reservation identity")
    root = Path(state_root)
    if (
        not root.is_absolute()
        or root.resolve() != root
        or root.is_relative_to(CHECKOUT)
    ):
        raise ValueError("private external reservation root required")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    directory_fd = None
    held = []
    try:
        _private_directory(os.fstat(root_fd))
        with suppress(FileExistsError):
            os.mkdir(DIRECTORY, mode=0o700, dir_fd=root_fd)
        directory_fd = os.open(
            DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
        _private_directory(os.fstat(directory_fd))
        for device in sorted(devices):
            name = "netbox-device-" + device.rsplit(":", 1)[1] + ".lock"
            fd = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=directory_fd,
            )
            # Close the newly opened descriptor even if validation/flock fails.
            held.append(fd)
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or info.st_size != 0
            ):
                raise ValueError("rollout reservation file rejected")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("rollout device already reserved") from None
        yield tuple(sorted(devices))
    finally:
        # Closing descriptors releases all acquired locks on every path, including
        # partial acquisition and exceptions. Process exit provides the same release.
        for fd in reversed(held):
            os.close(fd)
        if directory_fd is not None:
            os.close(directory_fd)
        os.close(root_fd)
