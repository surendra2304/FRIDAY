from types import SimpleNamespace

from scripts.oci_a1_sniper import SHAPE, available_capacity, find_active_a1


def test_find_active_a1_skips_terminated_instances():
    instances = [
        SimpleNamespace(shape=SHAPE, lifecycle_state="TERMINATED", id="old"),
        SimpleNamespace(shape="VM.Standard.E2.1.Micro", lifecycle_state="RUNNING", id="amd"),
    ]
    assert find_active_a1(instances) is None


def test_find_active_a1_treats_provisioning_as_existing_to_prevent_duplicates():
    existing = SimpleNamespace(
        shape=SHAPE,
        lifecycle_state="PROVISIONING",
        id="new-instance",
    )
    assert find_active_a1([existing]) is existing


def test_available_capacity_filters_unavailable_and_zero_capacity():
    unavailable = SimpleNamespace(
        availability_status="OUT_OF_HOST_CAPACITY",
        available_count=0,
        fault_domain="FAULT-DOMAIN-1",
    )
    zero_capacity = SimpleNamespace(
        availability_status="AVAILABLE",
        available_count=0,
        fault_domain="FAULT-DOMAIN-2",
    )
    available = SimpleNamespace(
        availability_status="AVAILABLE",
        available_count=1,
        fault_domain="FAULT-DOMAIN-3",
    )
    assert available_capacity([unavailable, zero_capacity, available], "primary") == [
        available
    ]


def test_sniper_lanes_prefer_opposite_fault_domain_order():
    first = SimpleNamespace(
        availability_status="AVAILABLE",
        available_count=1,
        fault_domain="FAULT-DOMAIN-1",
    )
    last = SimpleNamespace(
        availability_status="AVAILABLE",
        available_count=1,
        fault_domain="FAULT-DOMAIN-3",
    )
    assert available_capacity([last, first], "primary") == [first, last]
    assert available_capacity([last, first], "fallback") == [last, first]
