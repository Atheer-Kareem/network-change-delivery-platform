"""Temporary external local locks only; never a device or persistent runtime."""

import fcntl
import os
import subprocess
import sys

import pytest

from network_change_delivery import profiled_rollout_reservation as locks

DEVICES = tuple(f"netbox:dcim.device:{i}" for i in (1, 2, 8, 9))


@pytest.fixture
def root(tmp_path):
    tmp_path.chmod(0o700)
    return tmp_path


def test_sorted_all_devices_compliant_included_and_unlocked_files_reusable(
    root, monkeypatch
):
    calls = []
    original = fcntl.flock

    def flock(fd, operation):
        assert operation == fcntl.LOCK_EX | fcntl.LOCK_NB
        calls.append(fd)
        return original(fd, operation)

    monkeypatch.setattr(fcntl, "flock", flock)
    with locks.reserve_rollout_devices(root, tuple(reversed(DEVICES))) as held:
        assert held == tuple(sorted(DEVICES)) and len(calls) == 4
        assert len(list((root / locks.DIRECTORY).glob("*.lock"))) == 4
        with (
            pytest.raises(ValueError, match="already reserved"),
            locks.reserve_rollout_devices(root, (DEVICES[-1],)),
        ):
            pass
        with locks.reserve_rollout_devices(root, ("netbox:dcim.device:99",)):
            pass
    for d in DEVICES:
        with locks.reserve_rollout_devices(root, (d,)):
            pass
    assert all(p.stat().st_size == 0 for p in (root / locks.DIRECTORY).iterdir())


def test_partial_failure_releases_previous_locks(root):
    with locks.reserve_rollout_devices(root, (DEVICES[-1],)):
        with pytest.raises(ValueError), locks.reserve_rollout_devices(root, DEVICES):
            pass
        with locks.reserve_rollout_devices(root, DEVICES[:-1]):
            pass
    with locks.reserve_rollout_devices(root, DEVICES):
        pass


def test_exception_releases_every_lock(root):
    with pytest.raises(RuntimeError), locks.reserve_rollout_devices(root, DEVICES):
        raise RuntimeError("bounded failure")
    with locks.reserve_rollout_devices(root, DEVICES):
        pass


@pytest.mark.parametrize(
    "devices",
    [
        (),
        ("netbox:dcim.device:1",) * 2,
        ("core-02",),
        ("192.0.2.1",),
        ("netbox:dcim.device:0",),
        ("netbox:dcim.device:../1",),
        "netbox:dcim.device:1",
    ],
)
def test_invalid_identity_fails_before_files(root, devices):
    with pytest.raises(ValueError), locks.reserve_rollout_devices(root, devices):
        pass
    assert not (root / locks.DIRECTORY).exists()


@pytest.mark.parametrize(
    "damage",
    [
        "root_mode",
        "root_symlink",
        "directory_mode",
        "directory_symlink",
        "file_mode",
        "file_symlink",
        "file_hardlink",
        "file_contents",
        "file_directory",
        "wrong_owner",
        "checkout",
    ],
)
def test_private_file_and_path_admission(root, monkeypatch, damage):
    directory = root / locks.DIRECTORY
    if damage == "root_mode":
        root.chmod(0o755)
    elif damage == "root_symlink":
        link = root.parent / (root.name + "-link")
        link.symlink_to(root)
        root = link
    elif damage == "wrong_owner":
        monkeypatch.setattr(os, "getuid", lambda: 999999)
    elif damage == "checkout":
        monkeypatch.setattr(locks, "CHECKOUT", root)
    else:
        directory.mkdir(mode=0o700)
        path = directory / "netbox-device-1.lock"
        if damage == "directory_mode":
            directory.chmod(0o755)
        elif damage == "directory_symlink":
            directory.rmdir()
            directory.symlink_to(root)
        elif damage == "file_directory":
            path.mkdir()
        else:
            target = root / "unrelated"
            target.write_bytes(b"")
            target.chmod(0o600)
            if damage == "file_symlink":
                path.symlink_to(target)
            elif damage == "file_hardlink":
                os.link(target, path)
            else:
                path.write_bytes(b"content" if damage == "file_contents" else b"")
                path.chmod(0o644 if damage == "file_mode" else 0o600)
    with (
        pytest.raises((ValueError, OSError)),
        locks.reserve_rollout_devices(root, DEVICES),
    ):
        pass


def test_kernel_process_reservation_and_exit_release(root):
    program = """import sys
from pathlib import Path
from network_change_delivery.profiled_rollout_reservation import reserve_rollout_devices
with reserve_rollout_devices(Path(sys.argv[1]), ("netbox:dcim.device:1",)):
 print("held", flush=True)
 sys.stdin.readline()
"""
    p = subprocess.Popen(
        [sys.executable, "-c", program, str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert p.stdout.readline().strip() == "held"
        with (
            pytest.raises(ValueError),
            locks.reserve_rollout_devices(root, (DEVICES[0],)),
        ):
            pass
        # Abrupt process exit releases the kernel lock even without Python cleanup.
        p.terminate()
        p.wait(timeout=10)
        with locks.reserve_rollout_devices(root, (DEVICES[0],)):
            pass
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)
        p.stdin.close()
        p.stdout.close()
