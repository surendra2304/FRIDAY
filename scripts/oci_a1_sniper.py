"""Single-attempt, rate-limit-aware allocator for the FRIDAY OCI A1 VM.

The two scheduled workflows provide retries; this worker performs one bounded
attempt per run. Credentials are supplied only through Actions secrets.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

SHAPE = "VM.Standard.A1.Flex"
TARGET_OCPUS = 2
TARGET_MEMORY_GB = 12
BOOT_VOLUME_GB = 50
DEFAULT_REGION = "ap-hyderabad-1"
DEFAULT_AVAILABILITY_DOMAIN = "qvRd:AP-HYDERABAD-1-AD-1"
# Non-secret resource identifiers carried forward from the previous local worker.
DEFAULT_SUBNET_ID = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaa2rox2pqtptjmmm6p6ddritbf6uxxa7zpeiicxwx6kbsydcfudibq"
DEFAULT_IMAGE_ID = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaacx5cw6qxwnemznb2wojrfdbkuepvgwzlwzqa2snxqslops3nmlua"
DEFAULT_SSH_PUBLIC_KEY = (
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDsKkIMQ/GEBLSdYRPkvO6k1f8PJF/Xeva6qbEz2aUmE9DzWAg473x+tyH3iwSxYsg6j/jw/KZvnj8cqlSWYPq+93H88gyi5+etoXmL3Ej4bpQalSboL91HOqiVgeXtzx4XKtuizmY+w6osOlJJQiW0nFiHyeKzDFWfE02P4ljvIku7Fe3O2tu531qzzLBjzDWHWS9LRb5TvQ9f3rHZSnCXs4RiAXSj1fEyjjMOFcIzyfyqeORMM/3816Vv4eQ6/6hrx7V127s8f+14JKQJfykQryDdcOvKjLons+wm61/yMKbQgFASIHHTIPVE3ZRedkEQP1Q80BWh15wm9USmMkgP ssh-key-2026-10-13"
)


def _set_output(name: str, value: object) -> None:
    """Write a short, single-line GitHub Actions output without log leakage."""
    text = re.sub(r"[^A-Za-z0-9_.:/ -]", "_", str(value)).replace("\n", " ").replace("\r", " ")
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={text}\n")


def _summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(markdown.rstrip() + "\n")


def find_active_a1(instances: list[Any]) -> Any | None:
    """Return an existing A1 instance unless OCI confirms it is terminated."""
    for instance in instances:
        if getattr(instance, "shape", None) != SHAPE:
            continue
        if str(getattr(instance, "lifecycle_state", "")).upper() != "TERMINATED":
            return instance
    return None


def has_target_resources(instance: Any) -> bool:
    """Return whether an A1 instance already meets the requested shape size."""
    shape_config = getattr(instance, "shape_config", None)
    try:
        ocpus = float(getattr(shape_config, "ocpus", 0) or 0)
        memory = float(getattr(shape_config, "memory_in_gbs", 0) or 0)
    except (TypeError, ValueError):
        return False
    return ocpus >= TARGET_OCPUS and memory >= TARGET_MEMORY_GB


def available_capacity(entries: list[Any], lane: str) -> list[Any]:
    """Return capacity rows with an available status and positive/unspecified count."""
    candidates = [
        entry
        for entry in entries
        if str(getattr(entry, "availability_status", "")).upper() == "AVAILABLE"
        and (
            getattr(entry, "available_count", None) is None
            or int(getattr(entry, "available_count")) > 0
        )
    ]
    candidates.sort(key=lambda entry: str(getattr(entry, "fault_domain", "") or ""))
    if lane == "fallback":
        candidates.reverse()
    return candidates


def _write_result(result: str, reason: str = "none", instance_id: str = "", state: str = "") -> None:
    _set_output("result", result)
    _set_output("reason", reason)
    _set_output("instance_id", instance_id)
    _set_output("instance_state", state)


def main() -> int:
    lane = os.environ.get("SNIPER_LANE", "primary").strip().lower()
    if lane not in {"primary", "fallback"}:
        lane = "primary"

    values = {
        "OCI_USER_OCID": os.environ.get("OCI_USER_OCID", "").strip(),
        "OCI_KEY_CONTENT": os.environ.get("OCI_KEY_CONTENT", "").strip(),
        "OCI_FINGERPRINT": os.environ.get("OCI_FINGERPRINT", "").strip(),
        "OCI_TENANCY_OCID": os.environ.get("OCI_TENANCY_OCID", "").strip(),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        reason = "missing_required_secrets_" + "_".join(missing)
        print("Sniper configuration is incomplete; required secret names: " + ", ".join(missing))
        _write_result("error", reason)
        _summary("## OCI A1 sniper\n\nStatus: **configuration error**. See the run log for missing secret names.")
        return 2

    tenancy_id = values["OCI_TENANCY_OCID"]
    compartment_id = os.environ.get("OCI_COMPARTMENT_OCID", "").strip() or tenancy_id
    region = os.environ.get("OCI_REGION", "").strip() or DEFAULT_REGION
    subnet_id = os.environ.get("OCI_SUBNET_ID", "").strip() or DEFAULT_SUBNET_ID
    image_id = os.environ.get("OCI_IMAGE_ID", "").strip() or DEFAULT_IMAGE_ID
    availability_domain = (
        os.environ.get("OCI_AVAILABILITY_DOMAIN", "").strip()
        or DEFAULT_AVAILABILITY_DOMAIN
    )
    ssh_public_key = os.environ.get("OCI_SSH_PUBLIC_KEY", "").strip() or DEFAULT_SSH_PUBLIC_KEY
    key_content = values["OCI_KEY_CONTENT"].replace("\\n", "\n")
    run_identity = f"{os.environ.get('GITHUB_RUN_ID', 'manual')}:{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    retry_token = hashlib.sha256(run_identity.encode("utf-8")).hexdigest()

    try:
        import oci  # Imported lazily so pure helper tests do not require the SDK.

        with tempfile.TemporaryDirectory(prefix="friday-oci-key-") as temporary_directory:
            key_path = Path(temporary_directory) / "oci_api_key.pem"
            key_path.write_text(key_content.rstrip() + "\n", encoding="utf-8")
            key_path.chmod(0o600)

            config = {
                "user": values["OCI_USER_OCID"],
                "fingerprint": values["OCI_FINGERPRINT"],
                "key_file": str(key_path),
                "tenancy": tenancy_id,
                "region": region,
            }
            passphrase = os.environ.get("OCI_KEY_PASSPHRASE", "")
            if passphrase:
                config["pass_phrase"] = passphrase
            oci.config.validate_config(config)

            # One API request per operation; transient failures are retried by
            # the next schedule instead of a nested/unbounded SDK retry loop.
            no_retry = oci.retry.NoneRetryStrategy()
            compute = oci.core.ComputeClient(
                config, retry_strategy=no_retry, timeout=(10, 25)
            )
            network = oci.core.VirtualNetworkClient(
                config, retry_strategy=no_retry, timeout=(10, 25)
            )

            instances = oci.pagination.list_call_get_all_results(
                compute.list_instances, compartment_id=compartment_id
            ).data
            existing = find_active_a1(instances)
            if existing is not None:
                state = str(getattr(existing, "lifecycle_state", "UNKNOWN"))
                instance_id = str(getattr(existing, "id", ""))
                shape_config = getattr(existing, "shape_config", None)
                ocpus = getattr(shape_config, "ocpus", "unknown")
                memory = getattr(shape_config, "memory_in_gbs", "unknown")
                print(
                    f"Existing A1 instance detected (state={state}, "
                    f"OCPUs={ocpus}, memory_gb={memory}); no duplicate launch attempted."
                )
                if not has_target_resources(existing):
                    print("Existing A1 instance is below the requested 2 OCPU / 12 GB target; manual review is required.")
                    _write_result(
                        "error", "existing_a1_below_target",
                        instance_id=instance_id, state=state
                    )
                    _summary(
                        "## OCI A1 sniper\n\n"
                        "Status: **existing A1 instance below target**. No duplicate launch or automatic resize was attempted. "
                        f"Observed resources: {ocpus} OCPUs / {memory} GB RAM; required: {TARGET_OCPUS} OCPUs / {TARGET_MEMORY_GB} GB RAM."
                    )
                    return 1
                _write_result("existing", instance_id=instance_id, state=state)
                _summary(
                    "## OCI A1 sniper\n\n"
                    f"Status: existing A1 instance meets the requested shape size (`{state}`). "
                    "No duplicate instance was requested."
                )
                return 0

            subnet = network.get_subnet(subnet_id).data
            if str(getattr(subnet, "lifecycle_state", "")).upper() != "AVAILABLE":
                print("Configured subnet is not AVAILABLE; no launch attempted.")
                _write_result("error", "subnet_not_available")
                return 2

            image = compute.get_image(image_id).data
            if str(getattr(image, "lifecycle_state", "")).upper() != "AVAILABLE":
                print("Configured image is not AVAILABLE; no launch attempted.")
                _write_result("error", "image_not_available")
                return 2

            # OCI's capacity-report API requires the tenancy/root compartment,
            # even when the instance launch is delegated to a child compartment.
            capacity_details = oci.core.models.CreateComputeCapacityReportDetails(
                compartment_id=tenancy_id,
                availability_domain=availability_domain,
                shape_availabilities=[
                    oci.core.models.CreateCapacityReportShapeAvailabilityDetails(
                        instance_shape=SHAPE,
                        instance_shape_config=oci.core.models.CapacityReportInstanceShapeConfig(
                            ocpus=TARGET_OCPUS,
                            memory_in_gbs=TARGET_MEMORY_GB,
                        ),
                    )
                ],
            )
            report = compute.create_compute_capacity_report(
                capacity_details, retry_strategy=no_retry
            ).data
            candidates = available_capacity(
                list(getattr(report, "shape_availabilities", []) or []), lane
            )
            if not candidates:
                print(
                    "No reported host capacity for the target A1 shape in this "
                    "availability domain; the next scheduled run will check again."
                )
                _write_result("no_capacity")
                _summary(
                    "## OCI A1 sniper\n\n"
                    "Status: no capacity reported for **2 OCPUs / 12 GB RAM**. "
                    "No launch request was sent; the next scheduled run will retry."
                )
                return 0

            selected = candidates[0]
            fault_domain = getattr(selected, "fault_domain", None)
            launch_details = oci.core.models.LaunchInstanceDetails(
                display_name="FRIDAY Universe ARM",
                compartment_id=compartment_id,
                availability_domain=availability_domain,
                shape=SHAPE,
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=TARGET_OCPUS,
                    memory_in_gbs=TARGET_MEMORY_GB,
                ),
                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    image_id=image_id,
                    boot_volume_size_in_gbs=BOOT_VOLUME_GB,
                    boot_volume_vpus_per_gb=10,
                ),
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    assign_public_ip=True,
                    display_name="FRIDAY Universe ARM VNIC",
                    subnet_id=subnet_id,
                ),
                metadata={"ssh_authorized_keys": ssh_public_key},
                is_pv_encryption_in_transit_enabled=True,
            )
            if fault_domain:
                launch_details.fault_domain = fault_domain

            response = compute.launch_instance(
                launch_details, opc_retry_token=retry_token
            )
            instance = response.data
            instance_id = str(getattr(instance, "id", ""))
            state = str(getattr(instance, "lifecycle_state", "PROVISIONING"))
            print(
                "OCI accepted the A1 launch request: "
                f"shape={SHAPE}, OCPUs={TARGET_OCPUS}, memory_gb={TARGET_MEMORY_GB}, "
                f"boot_gb={BOOT_VOLUME_GB}, state={state}."
            )
            _write_result("allocated", instance_id=instance_id, state=state)
            _summary(
                "## OCI A1 sniper\n\n"
                "Status: **allocation request accepted**.\n\n"
                f"- Shape: `{SHAPE}`\n"
                f"- Resources: {TARGET_OCPUS} OCPUs / {TARGET_MEMORY_GB} GB RAM\n"
                f"- Boot volume: {BOOT_VOLUME_GB} GB\n"
                f"- Lifecycle state at response: `{state}`\n"
                f"- Instance OCID: `{instance_id}`\n\n"
                "Confirm the next OCI inventory check reports the instance as running "
                "before treating it as deployment-ready."
            )
            return 0

    except Exception as exc:  # Deliberately suppress response bodies and credentials.
        status = getattr(exc, "status", None)
        code = str(getattr(exc, "code", type(exc).__name__))
        safe_code = re.sub(r"[^A-Za-z0-9_.-]", "_", code)[:60] or "unknown"
        reason = f"oci_error_{status or 'unknown'}_{safe_code}"
        print(
            "OCI sniper attempt failed; details were intentionally redacted. "
            f"status={status or 'unknown'} code={safe_code}."
        )
        _write_result("error", reason)
        _summary(
            "## OCI A1 sniper\n\n"
            "Status: **attempt failed**. Sensitive SDK details were suppressed. "
            f"Diagnostic code: `{reason}`. See this workflow run for the safe summary."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
