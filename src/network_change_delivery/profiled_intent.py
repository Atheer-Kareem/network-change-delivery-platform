"""Fixed committed intent selection and semantic planning-result admission."""

import os
import stat
from pathlib import Path

import yaml

from network_change_delivery.models import InterfaceDescriptionIntent
from network_change_delivery.profile_inventory import PROFILED_MANAGED_POPULATION
from network_change_delivery.profiled_planning import (
    ProfiledComplianceRecord,
    ProfiledDeploymentPlan,
)

ACTIVE_INTENT_PATH = Path("deployments/live/profiled-demo.yaml")
MAX_INTENT_BYTES = 16 * 1024


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate intent mapping key")
        return super().construct_mapping(node, deep=deep)


def load_committed_intent(checkout: Path) -> InterfaceDescriptionIntent:
    """Read only the fixed file inside the caller's admitted checkout, without links."""
    descriptors = []
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors.append(os.open(checkout, directory_flags))
        for part in ACTIVE_INTENT_PATH.parts[:-1]:
            descriptors.append(os.open(part, directory_flags, dir_fd=descriptors[-1]))
        descriptor = os.open(
            ACTIVE_INTENT_PATH.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=descriptors[-1],
        )
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_INTENT_BYTES:
            raise ValueError("intent file rejected")
        with os.fdopen(os.dup(descriptor), "rb") as source:
            content = source.read(MAX_INTENT_BYTES + 1)
        if len(content) != info.st_size:
            raise ValueError("intent size changed")
        intent = InterfaceDescriptionIntent.model_validate(
            yaml.load(content, Loader=_UniqueLoader)
        )
        PROFILED_MANAGED_POPULATION.member(intent.target)
        return intent
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        raise ValueError("committed deployment intent unavailable or invalid") from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def admit_intent_result(
    intent: InterfaceDescriptionIntent,
    result: ProfiledDeploymentPlan | ProfiledComplianceRecord,
) -> None:
    """Bind every supported intent field; result models own resolved device facts."""
    intent = InterfaceDescriptionIntent.model_validate(intent.model_dump())
    if (
        intent.change_id != result.change_id
        or intent.kind
        != (
            result.kind
            if isinstance(result, ProfiledDeploymentPlan)
            else result.operation.value
        )
        or intent.target != result.target
        or intent.interface != result.interface.name
        or intent.desired.description != result.desired_description
    ):
        raise ValueError("committed intent and planning result disagree")
