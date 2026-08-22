import pytest

from network_change_delivery.buildkite_policy import compare_approved_digests


def test_approval_values_are_exact() -> None:
    values = ("sha256:" + "a" * 64, "sha256:" + "b" * 64, "sha256:" + "c" * 64)
    compare_approved_digests(
        *values,
        approved_plan=values[0],
        approved_assurance=values[1],
        approved_promotion=values[2],
    )
    for index in range(3):
        changed = list(values)
        changed[index] = " " + changed[index]
        with pytest.raises(ValueError):
            compare_approved_digests(
                *values,
                approved_plan=changed[0],
                approved_assurance=changed[1],
                approved_promotion=changed[2],
            )
