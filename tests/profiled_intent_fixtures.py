"""Historical core demo values retained only as synthetic test data."""

from network_change_delivery.models import InterfaceDescriptionIntent

CHANGE_ID = "CHG-PROFILED-LAB-DEMO"
DESCRIPTION = "managed-by-ncdp-profiled-demo"


def historical_core_intent() -> InterfaceDescriptionIntent:
    """Match the immutable core plan fixtures independently of the active Git intent."""
    return InterfaceDescriptionIntent(
        change_id=CHANGE_ID,
        kind="interface_description",
        target="core-02",
        interface="GigabitEthernet2",
        desired={"description": DESCRIPTION},
    )
