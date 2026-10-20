"""Persistent OCI A1 allocator for the FRIDAY Universe AMD host.

Run as a systemd service using OCI Instance Principals. The process retries
capacity checks until the target instance reaches RUNNING, then exits cleanly.
No long-lived OCI API key is stored on the host.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.oci_a1_common import (
    BOOT_VOLUME_GB,
    DEFAULT_AVAILABILITY_DOMAIN,
    DEFAULT_IMAGE_ID,
    DEFAULT_REGION,
    DEFAULT_SSH_PUBLIC_KEY,
    DEFAULT_SUBNET_ID,
    SHAPE,
    TARGET_DISPLAY_NAME,
    TARGET_MEMORY_GB,
    TARGET_OCPUS,
    available_capacity,
    find_active_a1,
    has_target_resources,
)

NO_CAPACITY_SECONDS = 60
PENDING_INSTANCE_SECONDS = 20
TRANSIENT_ERROR_SECONDS = 120
RATE_LIMIT_SECONDS = 180
AUTH_OR_CONFIG_ERROR_SECONDS = 300
LOGGER = logging.getLogger("friday.oci_a1_allocator")
_STOP = threading.Event()


@dataclass(frozen=True)
class AttemptResult:
    """Outcome of one allocation cycle."""

    outcome: str
    delay_seconds: int = NO_CAPACITY_SECONDS
    complete: bool = False


def utc_now() -> str:
    """Return an explicit UTC timestamp suitable for durable state and logs."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_error(exc: Exception) -> tuple[int | None, str]:
    """Extract only bounded diagnostic identifiers, never response bodies."""
    status = getattr(exc, "status", None)
    code = str(getattr(exc, "code", type(exc).__name__))
    safe_code = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in code)[:60]
    return status if isinstance(status, int) else None, safe_code or "unknown"


def is_capacity_error(exc: Exception) -> bool:
    """Identify whether an exception represents temporary OCI host capacity exhaustion."""
    status = getattr(exc, "status", None)
    code = str(getattr(exc, "code", ""))
    msg = str(getattr(exc, "message", exc)).lower()
    if status in (500, 503, 409, 404):
        if any(term in msg for term in ("out of host capacity", "capacity", "not authorized or not found")):
            return True
        if any(term in code.lower() for term in ("outofhostcapacity", "outofcapacity", "internalerror", "serviceerror")):
            return True
    return False


def error_delay(status: int | None, code: str) -> int:
    """Back off for throttling/auth faults without abandoning the search."""
    if status == 429 or "TooManyRequests" in code:
        return RATE_LIMIT_SECONDS
    if status in (400, 401, 403) or "NotAuthorized" in code or "InvalidParameter" in code:
        return AUTH_OR_CONFIG_ERROR_SECONDS
    return TRANSIENT_ERROR_SECONDS


def persist_state(outcome: str, details: dict[str, Any] | None = None) -> None:
    """Atomically persist non-secret progress for service diagnostics."""
    state_directory = os.environ.get("STATE_DIRECTORY", "").strip()
    if not state_directory:
        return
    target_directory = Path(state_directory)
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / "state.json"
    temporary = target_directory / "state.json.tmp"
    document = {
        "updated_at": utc_now(),
        "outcome": outcome,
        "target": {
            "shape": SHAPE,
            "ocpus": TARGET_OCPUS,
            "memory_gb": TARGET_MEMORY_GB,
            "boot_volume_gb": BOOT_VOLUME_GB,
            "region": os.environ.get("OCI_REGION", DEFAULT_REGION),
        },
        "details": details or {},
    }
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


class ContinuousAllocator:
    """One API attempt per cycle, with persistent retries managed by run_forever."""

    def __init__(
        self,
        *,
        oci_module: Any | None = None,
        signer: Any | None = None,
        compute: Any | None = None,
        network: Any | None = None,
    ) -> None:
        self.oci = oci_module
        self.signer = signer
        self.compute = compute
        self.network = network
        self.region = os.environ.get("OCI_REGION", DEFAULT_REGION).strip() or DEFAULT_REGION
        self.availability_domain = (
            os.environ.get("OCI_AVAILABILITY_DOMAIN", "").strip()
            or DEFAULT_AVAILABILITY_DOMAIN
        )
        self.subnet_id = os.environ.get("OCI_SUBNET_ID", "").strip() or DEFAULT_SUBNET_ID
        self.image_id = os.environ.get("OCI_IMAGE_ID", "").strip() or DEFAULT_IMAGE_ID
        self.ssh_public_key = (
            os.environ.get("OCI_SSH_PUBLIC_KEY", "").strip() or DEFAULT_SSH_PUBLIC_KEY
        )
        self.target_ocpus = int(os.environ.get("OCI_TARGET_OCPUS", TARGET_OCPUS))
        self.target_memory_gb = int(os.environ.get("OCI_TARGET_MEMORY_GB", TARGET_MEMORY_GB))
        self.retry_seconds = int(os.environ.get("OCI_RETRY_INTERVAL", NO_CAPACITY_SECONDS))

    def connect(self) -> None:
        """Create OCI clients using the VM's Instance Principal identity."""
        if self.compute is not None and self.network is not None:
            return
        import oci

        self.oci = oci
        self.signer = self.signer or oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        config = {"region": self.region}
        no_retry = oci.retry.NoneRetryStrategy()
        self.compute = oci.core.ComputeClient(
            config, signer=self.signer, retry_strategy=no_retry, timeout=(10, 25)
        )
        self.network = oci.core.VirtualNetworkClient(
            config, signer=self.signer, retry_strategy=no_retry, timeout=(10, 25)
        )

    def _record(self, outcome: str, **details: Any) -> AttemptResult:
        persist_state(outcome, details)
        LOGGER.info("allocator_outcome=%s details=%s", outcome, json.dumps(details, sort_keys=True))
        return AttemptResult(outcome=outcome)

    def attempt_once(self) -> AttemptResult:
        """Inspect inventory and attempt allocation once if no target VM exists."""
        try:
            self.connect()
            tenancy_id = str(
                getattr(self.signer, "tenancy_id", "")
                or os.environ.get("OCI_TENANCY_OCID", "").strip()
            )
            if not tenancy_id:
                LOGGER.error("OCI instance principal did not expose a tenancy ID.")
                self._record(
                    "configuration_error",
                    diagnostic="missing_tenancy_id",
                    retry_seconds=AUTH_OR_CONFIG_ERROR_SECONDS,
                )
                return AttemptResult("configuration_error", AUTH_OR_CONFIG_ERROR_SECONDS)
            compartment_id = os.environ.get("OCI_COMPARTMENT_OCID", "").strip() or tenancy_id

            # List both the tenancy root and target compartment. OCI list APIs
            # are not recursive, so a dedicated target compartment must not hide
            # an existing A1 in the root compartment. De-duplicate by OCID when
            # the target compartment is the tenancy itself.
            inventory_compartments = [tenancy_id]
            if compartment_id != tenancy_id:
                inventory_compartments.append(compartment_id)
            inventory_by_id: dict[str, Any] = {}
            for inventory_compartment in inventory_compartments:
                listed = self.oci.pagination.list_call_get_all_results(
                    self.compute.list_instances,
                    compartment_id=inventory_compartment,
                ).data
                for item in listed:
                    item_id = str(getattr(item, "id", "") or "")
                    if item_id:
                        inventory_by_id[item_id] = item
            existing = find_active_a1(list(inventory_by_id.values()))
            if existing is not None:
                instance_id = str(getattr(existing, "id", ""))
                state = str(getattr(existing, "lifecycle_state", "UNKNOWN")).upper()
                display_name = str(getattr(existing, "display_name", "") or "")
                shape_config = getattr(existing, "shape_config", None)
                ocpus = getattr(shape_config, "ocpus", None)
                memory = getattr(shape_config, "memory_in_gbs", None)
                details = {
                    "instance_id": instance_id,
                    "display_name": display_name,
                    "lifecycle_state": state,
                    "ocpus": ocpus,
                    "memory_gb": memory,
                }
                if display_name != TARGET_DISPLAY_NAME:
                    persist_state("manual_review", {**details, "diagnostic": "unrelated_a1_instance"})
                    LOGGER.error(
                        "An unrelated A1 instance exists; refusing to misreport it as the FRIDAY target or launch a duplicate."
                    )
                    return AttemptResult("manual_review", AUTH_OR_CONFIG_ERROR_SECONDS)
                if not has_target_resources(existing):
                    persist_state("manual_review", details)
                    LOGGER.error(
                        "The FRIDAY A1 instance exists below target size; refusing to create a duplicate."
                    )
                    return AttemptResult("manual_review", AUTH_OR_CONFIG_ERROR_SECONDS)
                if state == "RUNNING":
                    persist_state("allocated_running", details)
                    LOGGER.info("Target ARM instance is RUNNING; allocation objective is complete.")
                    return AttemptResult("allocated_running", 0, True)
                if state == "STOPPED":
                    self.compute.instance_action(instance_id, "START")
                    self._record("existing_instance_start_requested", **details)
                    return AttemptResult("instance_pending", PENDING_INSTANCE_SECONDS)
                if state in {"PROVISIONING", "STARTING", "STOPPING", "TERMINATING"}:
                    self._record("instance_pending", **details)
                    return AttemptResult("instance_pending", PENDING_INSTANCE_SECONDS)
                self._record("existing_instance_requires_attention", **details)
                return AttemptResult("existing_instance_requires_attention", AUTH_OR_CONFIG_ERROR_SECONDS)

            subnet = self.network.get_subnet(self.subnet_id).data
            if str(getattr(subnet, "lifecycle_state", "")).upper() != "AVAILABLE":
                self._record("configuration_error", diagnostic="subnet_not_available")
                return AttemptResult("configuration_error", AUTH_OR_CONFIG_ERROR_SECONDS)
            image = self.compute.get_image(self.image_id).data
            if str(getattr(image, "lifecycle_state", "")).upper() != "AVAILABLE":
                self._record("configuration_error", diagnostic="image_not_available")
                return AttemptResult("configuration_error", AUTH_OR_CONFIG_ERROR_SECONDS)

            capacity_details = self.oci.core.models.CreateComputeCapacityReportDetails(
                compartment_id=tenancy_id,
                availability_domain=self.availability_domain,
                shape_availabilities=[
                    self.oci.core.models.CreateCapacityReportShapeAvailabilityDetails(
                        instance_shape=SHAPE,
                        instance_shape_config=self.oci.core.models.CapacityReportInstanceShapeConfig(
                            ocpus=TARGET_OCPUS,
                            memory_in_gbs=TARGET_MEMORY_GB,
                        ),
                    )
                ],
            )
            report = self.compute.create_compute_capacity_report(capacity_details).data
            capacity_entries = list(getattr(report, "shape_availabilities", []) or [])
            candidates = available_capacity(capacity_entries, "primary")
            if not candidates:
                # Only classify a shortage when OCI returned a non-empty,
                # recognized capacity result. Empty payloads and unsupported /
                # unknown statuses indicate a report/configuration problem;
                # don't hide them as no_capacity.
                if not capacity_entries:
                    diagnostic = "empty_shape_availabilities"
                else:
                    statuses = {
                        str(getattr(entry, "availability_status", "UNKNOWN")).upper()
                        for entry in capacity_entries
                    }
                    if "HARDWARE_NOT_SUPPORTED" in statuses:
                        diagnostic = "hardware_not_supported"
                    elif not statuses.issubset({"AVAILABLE", "OUT_OF_HOST_CAPACITY"}):
                        diagnostic = "unknown_availability_status"
                    else:
                        diagnostic = ""
                if diagnostic:
                    self._record(
                        "capacity_report_unusable",
                        diagnostic=diagnostic,
                        retry_seconds=AUTH_OR_CONFIG_ERROR_SECONDS,
                    )
                    return AttemptResult(
                        "capacity_report_unusable", AUTH_OR_CONFIG_ERROR_SECONDS
                    )
                if hasattr(self.compute, "launch_instance"):
                    candidate_domains = [None, "FAULT-DOMAIN-1", "FAULT-DOMAIN-2", "FAULT-DOMAIN-3"]
                    capacity_exhausted = False
                    for fault_domain in candidate_domains:
                        launch_details = self.oci.core.models.LaunchInstanceDetails(
                            display_name=TARGET_DISPLAY_NAME,
                            compartment_id=compartment_id,
                            availability_domain=self.availability_domain,
                            shape=SHAPE,
                            shape_config=self.oci.core.models.LaunchInstanceShapeConfigDetails(
                                ocpus=self.target_ocpus,
                                memory_in_gbs=self.target_memory_gb,
                            ),
                            source_details=self.oci.core.models.InstanceSourceViaImageDetails(
                                image_id=self.image_id,
                                boot_volume_size_in_gbs=BOOT_VOLUME_GB,
                                boot_volume_vpus_per_gb=10,
                            ),
                            create_vnic_details=self.oci.core.models.CreateVnicDetails(
                                assign_public_ip=True,
                                display_name="FRIDAY Universe ARM VNIC",
                                subnet_id=self.subnet_id,
                            ),
                            metadata={"ssh_authorized_keys": self.ssh_public_key},
                            is_pv_encryption_in_transit_enabled=True,
                        )
                        if fault_domain:
                            launch_details.fault_domain = fault_domain

                        ssh_key_fingerprint = hashlib.sha256(
                            self.ssh_public_key.encode("utf-8")
                        ).hexdigest()
                        token_input = (
                            f"friday-a1|{tenancy_id}|{compartment_id}|{self.region}|"
                            f"{self.availability_domain}|{fault_domain}|{self.target_ocpus}|"
                            f"{self.target_memory_gb}|{BOOT_VOLUME_GB}|{self.subnet_id}|"
                            f"{self.image_id}|{ssh_key_fingerprint}|{int(time.time() // 60)}"
                        )
                        retry_token = hashlib.sha256(token_input.encode("utf-8")).hexdigest()
                        try:
                            response = self.compute.launch_instance(
                                launch_details, opc_retry_token=retry_token
                            )
                            instance = response.data
                            instance_id = str(getattr(instance, "id", ""))
                            state = str(getattr(instance, "lifecycle_state", "PROVISIONING")).upper()
                            persist_state(
                                "launch_accepted",
                                {
                                    "instance_id": instance_id,
                                    "lifecycle_state": state,
                                    "fault_domain": fault_domain or "unspecified",
                                },
                            )
                            LOGGER.info(
                                "OCI accepted allocation request; instance_id=%s lifecycle_state=%s fault_domain=%s",
                                instance_id or "unknown",
                                state,
                                fault_domain or "unspecified",
                            )
                            return AttemptResult("launch_accepted", PENDING_INSTANCE_SECONDS)
                        except Exception as exc:
                            if is_capacity_error(exc):
                                LOGGER.info(
                                    "Candidate %s out of capacity (%s); checking next candidate...",
                                    fault_domain or "unspecified",
                                    str(getattr(exc, "message", exc))[:80],
                                )
                                capacity_exhausted = True
                                continue
                            raise

                self._record(
                    "no_capacity",
                    region=self.region,
                    availability_domain=self.availability_domain,
                    capacity_statuses=sorted(statuses),
                    retry_seconds=self.retry_seconds,
                    target_ocpus=self.target_ocpus,
                    target_memory_gb=self.target_memory_gb,
                )
                return AttemptResult("no_capacity", self.retry_seconds)

            for candidate in candidates:
                fault_domain = str(getattr(candidate, "fault_domain", "") or "")
                launch_details = self.oci.core.models.LaunchInstanceDetails(
                    display_name=TARGET_DISPLAY_NAME,
                    compartment_id=compartment_id,
                    availability_domain=self.availability_domain,
                    shape=SHAPE,
                    shape_config=self.oci.core.models.LaunchInstanceShapeConfigDetails(
                        ocpus=TARGET_OCPUS,
                        memory_in_gbs=TARGET_MEMORY_GB,
                    ),
                    source_details=self.oci.core.models.InstanceSourceViaImageDetails(
                        image_id=self.image_id,
                        boot_volume_size_in_gbs=BOOT_VOLUME_GB,
                        boot_volume_vpus_per_gb=10,
                    ),
                    create_vnic_details=self.oci.core.models.CreateVnicDetails(
                        assign_public_ip=True,
                        display_name="FRIDAY Universe ARM VNIC",
                        subnet_id=self.subnet_id,
                    ),
                    metadata={"ssh_authorized_keys": self.ssh_public_key},
                    is_pv_encryption_in_transit_enabled=True,
                )
                if fault_domain:
                    launch_details.fault_domain = fault_domain
                # Stable per fault-domain idempotency tokens prevent duplicate
                # launches if the API accepts a request but the client times out.
                ssh_key_fingerprint = hashlib.sha256(
                    self.ssh_public_key.encode("utf-8")
                ).hexdigest()
                token_input = (
                    f"friday-a1|{tenancy_id}|{compartment_id}|{self.region}|"
                    f"{self.availability_domain}|{fault_domain}|{TARGET_OCPUS}|"
                    f"{TARGET_MEMORY_GB}|{BOOT_VOLUME_GB}|{self.subnet_id}|"
                    f"{self.image_id}|{ssh_key_fingerprint}"
                )
                retry_token = hashlib.sha256(token_input.encode("utf-8")).hexdigest()
                try:
                    response = self.compute.launch_instance(
                        launch_details, opc_retry_token=retry_token
                    )
                    instance = response.data
                    instance_id = str(getattr(instance, "id", ""))
                    state = str(getattr(instance, "lifecycle_state", "PROVISIONING")).upper()
                    persist_state(
                        "launch_accepted",
                        {
                            "instance_id": instance_id,
                            "lifecycle_state": state,
                            "fault_domain": fault_domain,
                        },
                    )
                    LOGGER.info(
                        "OCI accepted allocation request; instance_id=%s lifecycle_state=%s fault_domain=%s",
                        instance_id or "unknown",
                        state,
                        fault_domain or "unspecified",
                    )
                    return AttemptResult("launch_accepted", PENDING_INSTANCE_SECONDS)
                except Exception as exc:
                    status, code = safe_error(exc)
                    if status == 409 or "OutOfHostCapacity" in code or "OutOfCapacity" in code:
                        LOGGER.warning(
                            "Fault domain %s rejected allocation for capacity/conflict; checking the next reported domain.",
                            fault_domain or "unspecified",
                        )
                        continue
                    raise
            self._record("launch_capacity_race", retry_seconds=NO_CAPACITY_SECONDS)
            return AttemptResult("launch_capacity_race", NO_CAPACITY_SECONDS)

        except Exception as exc:
            status, code = safe_error(exc)
            delay = error_delay(status, code)
            LOGGER.error(
                "OCI allocation attempt failed; status=%s code=%s retry_seconds=%s; SDK response details are redacted.",
                status if status is not None else "unknown",
                code,
                delay,
            )
            persist_state(
                "retrying_after_error",
                {"http_status": status, "diagnostic_code": code, "retry_seconds": delay},
            )
            return AttemptResult("retrying_after_error", delay)


def run_forever(
    allocator: Any,
    *,
    stop_event: Any = _STOP,
    wait: Callable[[float], Any] = time.sleep,
) -> int:
    """Retry until the VM is running or a stop signal is received."""
    while not stop_event.is_set():
        result = allocator.attempt_once()
        if result.complete:
            return 0
        LOGGER.info(
            "Search remains active; next attempt in %d seconds (outcome=%s).",
            result.delay_seconds,
            result.outcome,
        )
        if hasattr(stop_event, "wait"):
            stopped = stop_event.wait(result.delay_seconds)
        else:
            wait(result.delay_seconds)
            stopped = False
        if stopped:
            break
    LOGGER.info("Allocator stopped by a termination signal.")
    return 0


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, lambda *_: _STOP.set())
    signal.signal(signal.SIGINT, lambda *_: _STOP.set())
    LOGGER.info(
        "Starting continuous OCI A1 search: region=%s shape=%s OCPUs=%s RAM_GB=%s boot_GB=%s retry_on_no_capacity_seconds=%s",
        os.environ.get("OCI_REGION", DEFAULT_REGION),
        SHAPE,
        TARGET_OCPUS,
        TARGET_MEMORY_GB,
        BOOT_VOLUME_GB,
        NO_CAPACITY_SECONDS,
    )
    return run_forever(ContinuousAllocator())


if __name__ == "__main__":
    raise SystemExit(main())
