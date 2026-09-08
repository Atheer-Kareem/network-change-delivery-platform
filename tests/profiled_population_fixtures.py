"""Synthetic declarations reuse current profiles without onboarding lab devices."""

from copy import deepcopy

from test_profiled_population import devices, profiled_provider

from network_change_delivery.profile_inventory import (
    PROFILED_POPULATION_CATALOG,
    ProfiledPopulationDeclaration,
    ProfiledPopulationMember,
    population_scope,
)


def declared_population(size=4, *, repeated_profile_index=2):
    payloads = deepcopy(devices()[: min(size, 4)])
    members = list(PROFILED_POPULATION_CATALOG[: min(size, 4)])
    for index in range(4, size):
        original = PROFILED_POPULATION_CATALOG[repeated_profile_index]
        identity = 10 + index
        name = f"synthetic-{identity}"
        member = ProfiledPopulationMember.model_validate(
            {
                **original.model_dump(),
                "device_identity": f"netbox:dcim.device:{identity}",
                "logical_name": name,
            }
        )
        payload = deepcopy(devices()[repeated_profile_index])
        payload.update(id=identity, name=name)
        payload["primary_ip4"] = {
            "id": 1000 + identity,
            "address": f"192.0.2.{100 + identity}/24",
        }
        payloads.append(payload)
        members.append(member)
    declaration = ProfiledPopulationDeclaration(members=tuple(members))
    scope = population_scope(
        "synthetic-scope", declaration.identities, declaration=declaration
    )
    provider = profiled_provider(list(reversed(payloads)), declaration=declaration)
    return declaration, scope, provider, payloads


def typed_population_from_subjects(subjects, *, canonicalize=False):
    """Adapt transport-focused test subjects to the real resolved contract."""
    from network_change_delivery.inventory import InventoryError
    from network_change_delivery.profile_inventory import (
        ProfiledInventoryDevice,
        ProfiledInventoryPopulation,
    )

    templates = declared_population()[2].resolve_profiled_population().devices
    resolved = []
    try:
        for subject in subjects:
            identity = getattr(
                subject, "device_identity", getattr(subject, "inventory_object_id", "")
            )
            template = next(
                (d for d in templates if d.device_identity == identity), templates[0]
            )
            data = template.model_dump(mode="json")
            data.update(
                device_identity=identity,
                logical_name=subject.logical_name,
                expected_hostname=subject.logical_name,
                network_os=subject.network_os,
                automation_profile_id=subject.automation_profile_id,
            )
            data["platform"]["slug"] = subject.platform.slug
            binding = data["management_endpoints"]["live"]["binding"]["l3_endpoint"]
            binding["address"] = f"{subject.host}/24"
            if hasattr(subject, "port"):
                binding["port"] = subject.port
            resolved.append(ProfiledInventoryDevice.model_validate(data))
        if canonicalize:
            order = tuple(m.device_identity for m in PROFILED_POPULATION_CATALOG)
            resolved.sort(key=lambda d: order.index(d.device_identity))
        return ProfiledInventoryPopulation(devices=tuple(resolved))
    except (ValueError, AttributeError, KeyError) as error:
        raise InventoryError("test inventory population rejected") from error
