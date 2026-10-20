from types import SimpleNamespace

from scripts.oci_a1_continuous_allocator import (
    SHAPE,
    active_a1_instances,
    available_capacity,
    error_backoff,
    has_target_resources,
)


def _instance(shape=SHAPE, state="RUNNING", ocpus=2, memory=12):
    return SimpleNamespace(
        shape=shape,
        lifecycle_state=state,
        shape_config=SimpleNamespace(ocpus=ocpus, memory_in_gbs=memory),
    )


def test_active_a1_skips_terminated_but_prevents_duplicate_launches():
    terminated = _instance(state="TERMINATED")
    provisioning = _instance(state="PROVISIONING")
    assert active_a1_instances([terminated, provisioning]) == [provisioning]


def test_non_a1_instances_do_not_block_target_allocation():
    amd = _instance(shape="VM.Standard.E2.1.Micro", ocpus=1, memory=1)
    assert active_a1_instances([amd]) == []


def test_target_resource_check_requires_both_cpu_and_memory():
    assert has_target_resources(_instance(ocpus=2, memory=12))
    assert not has_target_resources(_instance(ocpus=1, memory=12))
    assert not has_target_resources(_instance(ocpus=2, memory=8))


def test_capacity_filters_unavailable_and_zero_capacity_rows():
    rows = [
        SimpleNamespace(availability_status="AVAILABLE", available_count=1, fault_domain="FD-2"),
        SimpleNamespace(availability_status="AVAILABLE", available_count=0, fault_domain="FD-1"),
        SimpleNamespace(availability_status="NOT_AVAILABLE", available_count=3, fault_domain="FD-3"),
        SimpleNamespace(availability_status="AVAILABLE", available_count=None, fault_domain="FD-1"),
    ]
    assert [row.fault_domain for row in available_capacity(rows)] == ["FD-1", "FD-2"]


def test_error_backoff_grows_and_is_capped():
    assert error_backoff(1) == 30
    assert error_backoff(2) == 60
    assert error_backoff(10) == 600
    assert error_backoff(99) == 600
