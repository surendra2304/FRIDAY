import json
from pathlib import Path
from types import SimpleNamespace

from scripts.oci_a1_continuous import (
    AUTH_OR_CONFIG_ERROR_SECONDS,
    NO_CAPACITY_SECONDS,
    RATE_LIMIT_SECONDS,
    TRANSIENT_ERROR_SECONDS,
    AttemptResult,
    error_delay,
    persist_state,
    run_forever,
    safe_error,
)


class FakeStopEvent:
    def __init__(self):
        self.delays = []
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.delays.append(seconds)
        return self.stopped


class FakeAllocator:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    def attempt_once(self):
        self.calls += 1
        return next(self.outcomes)


def test_retry_loop_continues_until_running_and_never_sleeps_after_success():
    allocator = FakeAllocator(
        [
            AttemptResult("no_capacity", NO_CAPACITY_SECONDS),
            AttemptResult("retrying_after_error", TRANSIENT_ERROR_SECONDS),
            AttemptResult("allocated_running", 0, True),
        ]
    )
    stop_event = FakeStopEvent()

    assert run_forever(allocator, stop_event=stop_event) == 0
    assert allocator.calls == 3
    assert stop_event.delays == [NO_CAPACITY_SECONDS, TRANSIENT_ERROR_SECONDS]


def test_retry_loop_continues_across_repeated_no_capacity_results():
    allocator = FakeAllocator(
        [
            AttemptResult("no_capacity", NO_CAPACITY_SECONDS),
            AttemptResult("no_capacity", NO_CAPACITY_SECONDS),
            AttemptResult("allocated_running", 0, True),
        ]
    )
    stop_event = FakeStopEvent()

    run_forever(allocator, stop_event=stop_event)

    assert allocator.calls == 3
    assert stop_event.delays == [NO_CAPACITY_SECONDS, NO_CAPACITY_SECONDS]


def test_error_backoff_distinguishes_rate_limit_authorization_and_transient():
    assert error_delay(429, "TooManyRequests") == RATE_LIMIT_SECONDS
    assert error_delay(403, "NotAuthorizedOrNotFound") == AUTH_OR_CONFIG_ERROR_SECONDS
    assert error_delay(503, "ServiceError") == TRANSIENT_ERROR_SECONDS


def test_safe_error_returns_only_bounded_status_and_sanitized_code():
    exc = RuntimeError("secret response body must never be returned")
    exc.status = 403
    exc.code = "NotAuthorized / <unsafe>"
    status, code = safe_error(exc)

    assert status == 403
    assert code == "NotAuthorized____unsafe_"
    assert "secret response body" not in code


def test_state_persistence_is_atomic_and_contains_no_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("OCI_REGION", "ap-hyderabad-1")

    persist_state(
        "no_capacity",
        {"diagnostic": "capacity unavailable", "secret_value_must_not_be_passed": "not a secret"},
    )

    state = json.loads((Path(tmp_path) / "state.json").read_text(encoding="utf-8"))
    assert state["outcome"] == "no_capacity"
    assert state["target"]["region"] == "ap-hyderabad-1"
    assert state["details"]["diagnostic"] == "capacity unavailable"
    assert "OCI_KEY_CONTENT" not in json.dumps(state)
    assert not (Path(tmp_path) / "state.json.tmp").exists()


def _fake_oci_with_no_capacity():
    from scripts.oci_a1_common import SHAPE, TARGET_MEMORY_GB, TARGET_OCPUS

    def model(**kwargs):
        return SimpleNamespace(**kwargs)

    models = SimpleNamespace(
        CreateComputeCapacityReportDetails=model,
        CreateCapacityReportShapeAvailabilityDetails=model,
        CapacityReportInstanceShapeConfig=model,
        LaunchInstanceDetails=model,
        LaunchInstanceShapeConfigDetails=model,
        InstanceSourceViaImageDetails=model,
        CreateVnicDetails=model,
    )

    def paginate(call, **kwargs):
        return SimpleNamespace(data=call(**kwargs))

    oci = SimpleNamespace(
        pagination=SimpleNamespace(list_call_get_all_results=paginate),
        core=SimpleNamespace(models=models),
    )
    compute = SimpleNamespace(
        list_instances=lambda **_: [],
        get_image=lambda *_args, **_kwargs: SimpleNamespace(
            data=SimpleNamespace(lifecycle_state="AVAILABLE")
        ),
        create_compute_capacity_report=lambda *_args, **_kwargs: SimpleNamespace(
            data=SimpleNamespace(
                shape_availabilities=[
                    model(
                        availability_status="OUT_OF_HOST_CAPACITY",
                        available_count=0,
                        fault_domain="FAULT-DOMAIN-1",
                        instance_shape=SHAPE,
                        instance_shape_config=model(
                            ocpus=TARGET_OCPUS, memory_in_gbs=TARGET_MEMORY_GB
                        ),
                    )
                ]
            )
        ),
    )
    network = SimpleNamespace(
        get_subnet=lambda *_args, **_kwargs: SimpleNamespace(
            data=SimpleNamespace(lifecycle_state="AVAILABLE")
        )
    )
    signer = SimpleNamespace(tenancy_id="ocid1.tenancy.test")
    return oci, signer, compute, network


def test_allocator_reports_no_capacity_and_keeps_retry_delay(tmp_path, monkeypatch):
    from scripts.oci_a1_continuous import ContinuousAllocator

    oci, signer, compute, network = _fake_oci_with_no_capacity()
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    allocator = ContinuousAllocator(
        oci_module=oci, signer=signer, compute=compute, network=network
    )

    result = allocator.attempt_once()

    assert result.outcome == "no_capacity"
    assert result.delay_seconds == NO_CAPACITY_SECONDS
    assert not result.complete
    assert json.loads((Path(tmp_path) / "state.json").read_text())["outcome"] == "no_capacity"


def test_allocator_does_not_label_empty_capacity_report_as_no_capacity(tmp_path, monkeypatch):
    from scripts.oci_a1_continuous import AUTH_OR_CONFIG_ERROR_SECONDS, ContinuousAllocator

    oci, signer, compute, network = _fake_oci_with_no_capacity()
    compute.create_compute_capacity_report = lambda *_args, **_kwargs: SimpleNamespace(
        data=SimpleNamespace(shape_availabilities=[])
    )
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    allocator = ContinuousAllocator(oci_module=oci, signer=signer, compute=compute, network=network)

    result = allocator.attempt_once()

    state = json.loads((Path(tmp_path) / "state.json").read_text())
    assert result.outcome == "capacity_report_unusable"
    assert result.delay_seconds == AUTH_OR_CONFIG_ERROR_SECONDS
    assert state["outcome"] == "capacity_report_unusable"
    assert state["details"]["diagnostic"] == "empty_shape_availabilities"


def test_allocator_does_not_label_unknown_capacity_status_as_no_capacity(tmp_path, monkeypatch):
    from scripts.oci_a1_continuous import AUTH_OR_CONFIG_ERROR_SECONDS, ContinuousAllocator

    oci, signer, compute, network = _fake_oci_with_no_capacity()
    compute.create_compute_capacity_report = lambda *_args, **_kwargs: SimpleNamespace(
        data=SimpleNamespace(shape_availabilities=[SimpleNamespace(availability_status="UNKNOWN_ENUM_VALUE", available_count=0)])
    )
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    allocator = ContinuousAllocator(oci_module=oci, signer=signer, compute=compute, network=network)

    result = allocator.attempt_once()

    state = json.loads((Path(tmp_path) / "state.json").read_text())
    assert result.outcome == "capacity_report_unusable"
    assert result.delay_seconds == AUTH_OR_CONFIG_ERROR_SECONDS
    assert state["details"]["diagnostic"] == "unknown_availability_status"


def test_allocator_distinguishes_hardware_not_supported_from_capacity_shortage(tmp_path, monkeypatch):
    from scripts.oci_a1_continuous import AUTH_OR_CONFIG_ERROR_SECONDS, ContinuousAllocator

    oci, signer, compute, network = _fake_oci_with_no_capacity()
    compute.create_compute_capacity_report = lambda *_args, **_kwargs: SimpleNamespace(
        data=SimpleNamespace(shape_availabilities=[SimpleNamespace(availability_status="HARDWARE_NOT_SUPPORTED", available_count=0)])
    )
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    allocator = ContinuousAllocator(oci_module=oci, signer=signer, compute=compute, network=network)

    result = allocator.attempt_once()

    state = json.loads((Path(tmp_path) / "state.json").read_text())
    assert result.outcome == "capacity_report_unusable"
    assert result.delay_seconds == AUTH_OR_CONFIG_ERROR_SECONDS
    assert state["details"]["diagnostic"] == "hardware_not_supported"


def test_allocator_does_not_launch_duplicate_for_running_target_vm():
    from scripts.oci_a1_continuous import ContinuousAllocator
    from scripts.oci_a1_common import SHAPE

    instance = SimpleNamespace(
        shape=SHAPE,
        lifecycle_state="RUNNING",
        display_name="FRIDAY Universe ARM",
        id="ocid1.instance.target",
        shape_config=SimpleNamespace(ocpus=2, memory_in_gbs=12),
    )
    oci, signer, compute, network = _fake_oci_with_no_capacity()
    compute.list_instances = lambda **_: [instance]
    allocator = ContinuousAllocator(
        oci_module=oci, signer=signer, compute=compute, network=network
    )

    result = allocator.attempt_once()

    assert result.outcome == "allocated_running"
    assert result.complete
    assert not hasattr(compute, "launch_instance")


def test_allocator_refuses_duplicate_if_existing_a1_is_undersized():
    from scripts.oci_a1_continuous import ContinuousAllocator
    from scripts.oci_a1_common import SHAPE

    instance = SimpleNamespace(
        shape=SHAPE,
        lifecycle_state="RUNNING",
        display_name="FRIDAY Universe ARM",
        id="ocid1.instance.undersized",
        shape_config=SimpleNamespace(ocpus=1, memory_in_gbs=6),
    )
    oci, signer, compute, network = _fake_oci_with_no_capacity()
    compute.list_instances = lambda **_: [instance]
    allocator = ContinuousAllocator(
        oci_module=oci, signer=signer, compute=compute, network=network
    )

    result = allocator.attempt_once()

    assert result.outcome == "manual_review"
    assert not result.complete
    assert not hasattr(compute, "launch_instance")



def test_allocator_refuses_to_claim_unrelated_a1_instance():
    from scripts.oci_a1_continuous import ContinuousAllocator
    from scripts.oci_a1_common import SHAPE

    instance = SimpleNamespace(
        shape=SHAPE,
        lifecycle_state="RUNNING",
        display_name="Unrelated A1 instance",
        id="ocid1.instance.other",
        shape_config=SimpleNamespace(ocpus=2, memory_in_gbs=12),
    )
    oci, signer, compute, network = _fake_oci_with_no_capacity()
    compute.list_instances = lambda **_: [instance]
    allocator = ContinuousAllocator(
        oci_module=oci, signer=signer, compute=compute, network=network
    )

    result = allocator.attempt_once()

    assert result.outcome == "manual_review"
    assert not result.complete
    assert not hasattr(compute, "launch_instance")


def test_allocator_starts_stopped_target_and_keeps_polling():
    from scripts.oci_a1_continuous import ContinuousAllocator
    from scripts.oci_a1_common import SHAPE, TARGET_DISPLAY_NAME

    instance = SimpleNamespace(
        shape=SHAPE,
        lifecycle_state="STOPPED",
        display_name=TARGET_DISPLAY_NAME,
        id="ocid1.instance.stopped",
        shape_config=SimpleNamespace(ocpus=2, memory_in_gbs=12),
    )
    oci, signer, compute, network = _fake_oci_with_no_capacity()
    compute.list_instances = lambda **_: [instance]
    actions = []
    compute.instance_action = lambda instance_id, action: actions.append((instance_id, action))
    allocator = ContinuousAllocator(
        oci_module=oci, signer=signer, compute=compute, network=network
    )

    result = allocator.attempt_once()

    assert result.outcome == "instance_pending"
    assert result.delay_seconds > 0
    assert actions == [("ocid1.instance.stopped", "START")]


def test_allocator_scans_tenancy_root_and_target_compartment(monkeypatch):
    from scripts.oci_a1_continuous import ContinuousAllocator

    root_tenancy = "ocid1.tenancy.test"
    target_compartment = "ocid1.compartment.target"
    monkeypatch.setenv("OCI_COMPARTMENT_OCID", target_compartment)
    oci, signer, compute, network = _fake_oci_with_no_capacity()
    signer.tenancy_id = root_tenancy
    listed_compartments = []

    def list_instances(*, compartment_id):
        listed_compartments.append(compartment_id)
        return []

    compute.list_instances = list_instances
    allocator = ContinuousAllocator(
        oci_module=oci, signer=signer, compute=compute, network=network
    )

    result = allocator.attempt_once()

    assert result.outcome == "no_capacity"
    assert listed_compartments == [root_tenancy, target_compartment]

def test_is_capacity_error_identifies_500_internalerror_and_capacity_messages():
    from scripts.oci_a1_continuous import is_capacity_error

    exc1 = SimpleNamespace(status=500, code='InternalError', message='Out of host capacity.')
    assert is_capacity_error(exc1) is True

    exc2 = SimpleNamespace(status=409, code='OutOfHostCapacity', message='Capacity limit.')
    assert is_capacity_error(exc2) is True

    exc3 = SimpleNamespace(status=401, code='NotAuthorized', message='Bad key')
    assert is_capacity_error(exc3) is False


def test_allocator_attempts_direct_launch_when_capacity_report_is_empty(tmp_path, monkeypatch):
    from scripts.oci_a1_continuous import ContinuousAllocator
    from scripts.oci_a1_common import SHAPE

    oci, signer, compute, network = _fake_oci_with_no_capacity()
    # Report says OUT_OF_HOST_CAPACITY (standard free tier state)
    compute.create_compute_capacity_report = lambda *_args, **_kwargs: SimpleNamespace(
        data=SimpleNamespace(shape_availabilities=[SimpleNamespace(availability_status="OUT_OF_HOST_CAPACITY", available_count=0)])
    )
    monkeypatch.setenv('STATE_DIRECTORY', str(tmp_path))
    monkeypatch.setenv('OCI_RETRY_INTERVAL', '25')

    class MockServiceError(Exception):
        def __init__(self, status, code, message):
            self.status = status
            self.code = code
            self.message = message
            super().__init__(message)

    launch_calls = []
    def mock_launch(details, opc_retry_token=None):
        launch_calls.append((details, opc_retry_token))
        raise MockServiceError(500, 'InternalError', 'Out of host capacity.')

    compute.launch_instance = mock_launch
    allocator = ContinuousAllocator(
        oci_module=oci, signer=signer, compute=compute, network=network
    )

    result = allocator.attempt_once()
    assert result.outcome == 'no_capacity'
    assert result.delay_seconds == 25
    assert len(launch_calls) > 0
