"""Fixed reviewed rollout input; retained planning schemas are not reinterpreted."""

import os
import stat
from pathlib import Path

import yaml

from network_change_delivery.profiled_intent import _UniqueLoader
from network_change_delivery.profiled_rollout import ProfiledRolloutSelectionIntent

ACTIVE_ROLLOUT_INTENT_PATH = Path("deployments/live/profiled-rollout.yaml")
MAX_ROLLOUT_INTENT_BYTES = 64 * 1024


def load_committed_rollout_intent(checkout: Path) -> ProfiledRolloutSelectionIntent:
    """Read the fixed regular file with no-follow handling at every path component."""
    descriptors = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors.append(os.open(checkout, flags))
        for part in ACTIVE_ROLLOUT_INTENT_PATH.parts[:-1]:
            descriptors.append(os.open(part, flags, dir_fd=descriptors[-1]))
        fd = os.open(
            ACTIVE_ROLLOUT_INTENT_PATH.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=descriptors[-1],
        )
        descriptors.append(fd)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or not 0 < info.st_size <= MAX_ROLLOUT_INTENT_BYTES
        ):
            raise ValueError("rollout intent file rejected")
        with os.fdopen(os.dup(fd), "rb") as source:
            raw = source.read(MAX_ROLLOUT_INTENT_BYTES + 1)
        if len(raw) != info.st_size:
            raise ValueError("rollout intent size changed")
        return ProfiledRolloutSelectionIntent.model_validate(
            yaml.load(raw, Loader=_UniqueLoader)
        )
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        raise ValueError("committed rollout intent unavailable or invalid") from None
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
