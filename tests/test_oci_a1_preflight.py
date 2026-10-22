import json
from pathlib import Path
from types import SimpleNamespace

from scripts.oci_a1_preflight import load_env_file, run_preflight


def _fake_oci():
    def model(**kwargs):
        return SimpleNamespace(**kwargs)

    def paginate(call, **kwargs):
        return SimpleNamespace(data=call(**kwargs))

    models = SimpleNamespace(
        CreateComputeCapacityReportDetails=model,
        CreateCapacityReportShapeAvailabilityDetails=model,
        CapacityReportInstanceShapeConfig=model,
    )
    oci = SimpleNamespace(
        retry=SimpleNamespace(NoneRetryStrategy=lambda: object()),
        pagination=SimpleNamespace(list_call_get_all_results=paginate),
        core=SimpleNamespace(models=models),
    )
    compute = SimpleNamespace(
        list_instances=lambda **_: [],
        get_image=lambda *_a, **_kw: SimpleNamespace(
            data=SimpleNamespace(lifecycle_state="AVAILABLE")
        ),
        create_compute_capacity_report=lambda *_a, **_kw: SimpleNamespace(
            data=SimpleNamespace(shape_availabilities=[])
        ),
    )
    network = SimpleNamespace(
        get_subnet=lambda *_a, **_kw: SimpleNamespace(
            data=SimpleNamespace(lifecycle_state="AVAILABLE")
        )
    )
    signer = SimpleNamespace(tenancy_id="ocid1.tenancy.test")
    return oci, signer, compute, network


def test_env_file_only_reads_allowlisted_values_and_never_executes_shell(tmp_path):
    env_file = tmp_path / "allocator.env"
    env_file.write_text(
        "OCI_REGION=ap-hyderabad-1\n"
        "OCI_SUBNET_ID='subnet-value'\n"
        "UNKNOWN_KEY=$(touch /tmp/should-never-exist)\n",
        encoding="utf-8",
    )

    result = load_env_file(env_file, current={"OCI_REGION": "already-set"})

    assert result["OCI_REGION"] == "already-set"
    assert result["OCI_SUBNET_ID"] == "subnet-value"
    assert "UNKNOWN_KEY" not in result


def test_env_file_rejects_malformed_non_assignment_line(tmp_path):
    env_file = tmp_path / "allocator.env"
    env_file.write_text("this is not an assignment\n", encoding="utf-8")

    try:
        load_env_file(env_file, current={})
    except ValueError as exc:
        assert str(exc) == "invalid_environment_file_format"
    else:
        raise AssertionError("Malformed environment file must fail closed")


def test_preflight_passes_inventory_subnet_image_and_capacity_permissions():
    oci, signer, compute, network = _fake_oci()

    code, result = run_preflight(
        env={"OCI_REGION": "ap-hyderabad-1"},
        oci_module=oci,
        signer=signer,
        compute=compute,
        network=network,
    )

    assert code == 0
    assert result["status"] == "ready"
    assert result["checks"] == {
        "instance_inventory": "passed",
        "subnet": "available",
        "image": "available",
        "capacity_report_permission": "passed",
    }


def test_preflight_fails_closed_and_redacts_sdk_response_body():
    oci, signer, compute, network = _fake_oci()

    def denied(**_kwargs):
        error = RuntimeError("never emit credentials or response body")
        error.status = 404
        error.code = "NotAuthorizedOrNotFound"
        raise error

    compute.list_instances = denied

    code, result = run_preflight(
        env={},
        oci_module=oci,
        signer=signer,
        compute=compute,
        network=network,
    )

    rendered = json.dumps(result)
    assert code != 0
    assert result["status"] == "blocked"
    assert result["failed_check"] == "list_instances"
    assert result["http_status"] == 404
    assert result["diagnostic_code"] == "NotAuthorizedOrNotFound"
    assert "never emit credentials" not in rendered
