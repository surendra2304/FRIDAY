#!/usr/bin/env python3
"""Persistent OCI A1 allocator intended to run as a systemd service on the AMD VM.

No API private key is stored here: authentication uses OCI instance principals.
Capacity exhaustion is a normal retryable state. Authentication/configuration
failures are reported clearly and stop the process so they are not disguised as
capacity failures. The service resumes automatically after host/process restart.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SHAPE = "VM.Standard.A1.Flex"
TARGET_OCPUS = 2
TARGET_MEMORY_GB = 12
BOOT_VOLUME_GB = 50
DEFAULT_REGION = "ap-hyderabad-1"
DEFAULT_AVAILABILITY_DOMAIN = "qvRd:AP-HYDERABAD-1-AD-1"
DEFAULT_SUBNET_ID = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaa2rox2pqtptjmmm6p6ddritbf6uxxa7zpeiicxwx6kbsydcfudibq"
DEFAULT_IMAGE_ID = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaacx5cw6qxwnemznb2wojrfdbkuepvgwzlwzqa2snxqslops3nmlua"
DEFAULT_SSH_PUBLIC_KEY = (
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDsKkIMQ/GEBLSdYRPkvO6k1f8PJF/Xeva6qbEz2aUmE9DzWAg473x+tyH3iwSxYsg6j/jw/KZvnj8cqlSWYPq+93H88gyi5+etoXmL3Ej4bpQalSboL91HOqiVgeXtzx4XKtuizmY+w6osOlJJQiW0nFiHyeKzDFWfE02P4ljvIku7Fe3O2tu531qzzLBjzDWHWS9LRb5TvQ9f3rHZSnCXs4RiAXSj1fEyjjMOFcIzyfyqeORMM/3816Vv4eQ6/6hrx7V127s8f+14JKQJfykQryDdcOvKjLons+wm61/yMKbQgFASIHHTIPVE3ZRedkEQP1Q80BWh15wm9USmMkgP ssh-key-2026-10-13"
)
DEFAULT_STATE_PATH = "/var/lib/friday-oci-a1-allocator/state.json"
DEFAULT_POLL_SECONDS = 120
MAX_ERROR_BACKOFF_SECONDS = 600

LOG = logging.getLogger("friday.oci_a1_allocator")
_STOP = False


@dataclass(frozen=True)
class TargetConfig:
    compartment_id: str
    region: str
    availability_domain: str
    subnet_id: str
    image_id: str
    ssh_public_key: str
    state_path: Path
    poll_seconds: int


def config_from_env() -> TargetConfig:
    compartment = os.environ.get("OCI_COMPARTMENT_OCID", "").strip()
    tenancy = os.environ.get("OCI_TENANCY_OCID", "").strip()
    compartment = compartment or tenancy
    if not compartment:
        raise ValueError("OCI_COMPARTMENT_OCID or OCI_TENANCY_OCID is required")
    poll = int(os.environ.get("OCI_A1_POLL_SECONDS", str(DEFAULT_POLL_SECONDS)))
    if poll < 30:
        raise ValueError("OCI_A1_POLL_SECONDS must be at least 30 seconds")
    return TargetConfig(
        compartment_id=compartment,
        region=os.environ.get("OCI_REGION", DEFAULT_REGION).strip() or DEFAULT_REGION,
        availability_domain=(
            os.environ.get("OCI_AVAILABILITY_DOMAIN", DEFAULT_AVAILABILITY_DOMAIN).strip()
            or DEFAULT_AVAILABILITY_DOMAIN
        ),
        subnet_id=os.environ.get("OCI_SUBNET_ID", DEFAULT_SUBNET_ID).strip() or DEFAULT_SUBNET_ID,
        image_id=os.environ.get("OCI_IMAGE_ID", DEFAULT_IMAGE_ID).strip() or DEFAULT_IMAGE_ID,
        ssh_public_key=(
            os.environ.get("OCI_SSH_PUBLIC_KEY", DEFAULT_SSH_PUBLIC_KEY).strip()
            or DEFAULT_SSH_PUBLIC_KEY
        ),
        state_path=Path(os.environ.get("OCI_A1_STATE_PATH", DEFAULT_STATE_PATH)),
        poll_seconds=poll,
    )


def active_a1_instances(instances: list[Any]) -> list[Any]:
    """Return non-terminated A1 instances to prevent duplicate allocation."""
    return [
        instance
        for instance in instances
        if getattr(instance, "shape", None) == SHAPE
        and str(getattr(instance, "lifecycle_state", "")).upper() != "TERMINATED"
    ]


def has_target_resources(instance: Any) -> bool:
    shape_config = getattr(instance, "shape_config", None)
    try:
        ocpus = float(getattr(shape_config, "ocpus", 0) or 0)
        memory = float(getattr(shape_config, "memory_in_gbs", 0) or 0)
    except (TypeError, ValueError):
        return False
    return ocpus >= TARGET_OCPUS and memory >= TARGET_MEMORY_GB


def available_capacity(entries: list[Any]) -> list[Any]:
    candidates = [
        entry
        for entry in entries
        if str(getattr(entry, "availability_status", "")).upper() == "AVAILABLE"
        and (
            getattr(entry, "available_count", None) is None
            or int(getattr(entry, "available_count")) > 0
        )
    ]
    return sorted(candidates, key=lambda entry: str(getattr(entry, "fault_domain", "") or ""))


def error_backoff(attempt: int) -> int:
    """Bound transient-error retries to avoid tight loops and OCI API pressure."""
    return min(30 * (2 ** max(0, attempt - 1)), MAX_ERROR_BACKOFF_SECONDS)


def _read_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".state-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


def _make_compute_client(region: str) -> Any:
    try:
        import oci
    except ImportError as exc:
        raise RuntimeError("OCI SDK is not installed; install requirements-oci.txt") from exc
    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    if getattr(signer, "region", region) != region:
        LOG.warning("Configured OCI region differs from instance-principal region; using %s", region)
    return oci.core.ComputeClient(
        {"region": region},
        signer=signer,
        retry_strategy=oci.retry.NoneRetryStrategy(),
    )


class ContinuousAllocator:
    def __init__(
        self,
        config: TargetConfig,
        compute: Any,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.compute = compute
        self.clock = clock
        self.state = _read_state(config.state_path)
        self.error_count = 0

    def _save(self, status: str, **extra: Any) -> None:
        self.state.update(
            {
                "status": status,
                "updated_at_epoch": int(self.clock()),
                "target_shape": SHAPE,
                "target_ocpus": TARGET_OCPUS,
                "target_memory_gb": TARGET_MEMORY_GB,
                "boot_volume_gb": BOOT_VOLUME_GB,
            }
        )
        self.state.update(extra)
        _write_state(self.config.state_path, self.state)

    def _list_instances(self) -> list[Any]:
        response = self.compute.list_instances(
            compartment_id=self.config.compartment_id,
            retry_strategy=None,
        )
        return list(response.data or [])

    def _make_launch_details(self, fault_domain: str | None) -> Any:
        import oci

        details = oci.core.models.LaunchInstanceDetails(
            display_name="FRIDAY Universe ARM",
            compartment_id=self.config.compartment_id,
            availability_domain=self.config.availability_domain,
            shape=SHAPE,
            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=TARGET_OCPUS,
                memory_in_gbs=TARGET_MEMORY_GB,
            ),
            source_details=oci.core.models.InstanceSourceViaImageDetails(
                image_id=self.config.image_id,
                boot_volume_size_in_gbs=BOOT_VOLUME_GB,
                boot_volume_vpus_per_gb=10,
            ),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                assign_public_ip=True,
                display_name="FRIDAY Universe ARM VNIC",
                subnet_id=self.config.subnet_id,
            ),
            metadata={"ssh_authorized_keys": self.config.ssh_public_key},
            is_pv_encryption_in_transit_enabled=True,
        )
        if fault_domain:
            details.fault_domain = fault_domain
        return details

    def _launch(self, fault_domain: str | None) -> None:
        # Persist token and fault domain before submitting, so an ambiguous API
        # timeout can retry the same request idempotently after checking inventory.
        pending = self.state.get("pending_launch")
        if not isinstance(pending, dict) or pending.get("fault_domain") != fault_domain:
            pending = {
                "token": str(uuid.uuid4()),
                "fault_domain": fault_domain,
                "created_at_epoch": int(self.clock()),
            }
            self.state["pending_launch"] = pending
            self._save("launch_pending", pending_launch=pending)
        result = self.compute.launch_instance(
            self._make_launch_details(fault_domain),
            opc_retry_token=pending["token"],
            retry_strategy=None,
        ).data
        instance_id = str(getattr(result, "id", "") or "")
        lifecycle = str(getattr(result, "lifecycle_state", "PROVISIONING") or "PROVISIONING")
        self.state.pop("pending_launch", None)
        self._save(
            "allocation_accepted",
            instance_id=instance_id,
            lifecycle_state=lifecycle,
            fault_domain=fault_domain,
        )
        LOG.warning(
            "OCI accepted allocation request: instance_id_present=%s lifecycle=%s",
            bool(instance_id),
            lifecycle,
        )

    def tick(self) -> bool:
        instances = self._list_instances()
        active = active_a1_instances(instances)
        if active:
            instance = active[0]
            instance_id = str(getattr(instance, "id", "") or "")
            lifecycle = str(getattr(instance, "lifecycle_state", "UNKNOWN") or "UNKNOWN").upper()
            if has_target_resources(instance):
                if lifecycle == "RUNNING":
                    self.state.pop("pending_launch", None)
                    self._save(
                        "allocated",
                        instance_id=instance_id,
                        lifecycle_state=lifecycle,
                        display_name=getattr(instance, "display_name", "FRIDAY Universe ARM"),
                    )
                    LOG.warning("Target A1 allocation verified RUNNING; allocator goal achieved.")
                    return True
                self._save(
                    "allocation_in_progress",
                    instance_id=instance_id,
                    lifecycle_state=lifecycle,
                )
                LOG.info("A1 instance exists in lifecycle state %s; waiting without creating another.", lifecycle)
            else:
                self._save(
                    "manual_intervention_required",
                    instance_id=instance_id,
                    lifecycle_state=lifecycle,
                )
                LOG.error(
                    "A1 instance already exists but does not match 2 OCPUs / 12 GB RAM; "
                    "refusing to create a duplicate."
                )
            return False

        pending = self.state.get("pending_launch")
        if isinstance(pending, dict):
            # Retry the exact same launch request/token following an ambiguous result.
            self._launch(pending.get("fault_domain"))
            return False

        import oci

        details = oci.core.models.CreateComputeCapacityReportDetails(
            compartment_id=self.config.compartment_id,
            availability_domain=self.config.availability_domain,
            shape_availabilities=[
                oci.core.models.CapacityReportShapeAvailability(
                    instance_shape=SHAPE,
                    instance_shape_config=oci.core.models.CapacityReportInstanceShapeConfig(
                        ocpus=TARGET_OCPUS,
                        memory_in_gbs=TARGET_MEMORY_GB,
                    ),
                )
            ],
        )
        response = self.compute.create_compute_capacity_report(details, retry_strategy=None).data
        candidates = available_capacity(list(getattr(response, "shape_availabilities", []) or []))
        if not candidates:
            self._save("waiting_for_capacity", last_capacity_check_epoch=int(self.clock()))
            LOG.info(
                "No A1 host capacity reported; continuing search and retrying in %s seconds.",
                self.config.poll_seconds,
            )
            return False
        selected = candidates[0]
        self._launch(getattr(selected, "fault_domain", None))
        return False


def _handle_signal(signum: int, _frame: Any) -> None:
    global _STOP
    _STOP = True
    LOG.warning("Received shutdown signal %s; stopping cleanly.", signum)


def run_forever(config: TargetConfig, compute: Any | None = None) -> int:
    global _STOP
    if compute is None:
        compute = _make_compute_client(config.region)
    allocator = ContinuousAllocator(config, compute)
    _STOP = False
    error_count = 0
    while not _STOP:
        try:
            if allocator.tick():
                return 0
            error_count = 0
            delay = config.poll_seconds
        except Exception as exc:  # Do not emit SDK bodies, headers, tokens, or config values.
            status = getattr(exc, "status", None)
            code = str(getattr(exc, "code", type(exc).__name__))
            LOG.error(
                "Allocator iteration failed; status=%s error_code=%s. "
                "Sensitive SDK details were suppressed.",
                status if status is not None else "unknown",
                "".join(c if c.isalnum() or c in "._-" else "_" for c in code)[:60],
            )
            allocator._save("retrying_after_error", safe_error_code=code[:60])
            error_count += 1
            if status in (400, 401, 403):
                LOG.critical(
                    "OCI returned a non-retryable configuration/authorization response. "
                    "Stopping for operator correction; this is not a capacity failure."
                )
                return 2
            delay = error_backoff(error_count)
        LOG.info("Next check in %s seconds.", delay)
        end = time.monotonic() + delay
        while not _STOP and time.monotonic() < end:
            time.sleep(min(1, max(0, end - time.monotonic())))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one check only for diagnostics; the systemd service must omit this flag.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        config = config_from_env()
        compute = _make_compute_client(config.region)
        allocator = ContinuousAllocator(config, compute)
        if args.once:
            return 0 if allocator.tick() else 1
        return run_forever(config, compute)
    except ValueError as exc:
        LOG.critical("Invalid allocator configuration: %s", exc)
        return 2
    except Exception as exc:
        code = str(getattr(exc, "code", type(exc).__name__))
        LOG.critical(
            "Allocator could not initialize; error_code=%s. Sensitive details were suppressed.",
            "".join(c if c.isalnum() or c in "._-" else "_" for c in code)[:60],
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
