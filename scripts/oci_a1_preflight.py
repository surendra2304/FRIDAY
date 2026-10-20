"""Fail-closed preflight for the persistent OCI A1 allocator.

This validates the read/inspect permissions and target resources needed before
systemd is enabled. It never launches an instance and never emits SDK response
bodies, OCIDs, tokens, or other credential material.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ENV_FILE = Path("/etc/friday-arm-sniper.env")
ALLOWED_ENV_KEYS = {
    "OCI_REGION",
    "OCI_COMPARTMENT_OCID",
    "OCI_AVAILABILITY_DOMAIN",
    "OCI_SUBNET_ID",
    "OCI_IMAGE_ID",
    "OCI_SSH_PUBLIC_KEY",
}
ERROR_CODE_RE = re.compile(r"[^A-Za-z0-9_.-]")


def load_env_file(
    path: Path = ENV_FILE, current: dict[str, str] | None = None
) -> dict[str, str]:
    """Load only allow-listed KEY=value settings; never execute shell syntax."""
    values = dict(os.environ if current is None else current)
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("invalid_environment_file_format")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key not in ALLOWED_ENV_KEYS:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if "\n" in value or "\r" in value:
            raise ValueError("invalid_environment_file_value")
        # An already-exported environment variable wins over the optional file.
        values.setdefault(key, value)
    return values


def sanitized_error(exc: Exception) -> dict[str, Any]:
    """Return status/code only; never include exception strings or response data."""
    status = getattr(exc, "status", None)
    code = str(getattr(exc, "code", type(exc).__name__))
    safe_code = ERROR_CODE_RE.sub("_", code)[:60] or "unknown"
    return {
        "http_status": status if isinstance(status, int) else None,
        "diagnostic_code": safe_code,
    }


def run_preflight(
    *,
    env: dict[str, str] | None = None,
    oci_module: Any | None = None,
    signer: Any | None = None,
    compute: Any | None = None,
    network: Any | None = None,
) -> tuple[int, dict[str, Any]]:
    """Check instance inventory, subnet, image, and capacity-report permission."""
    from scripts.oci_a1_common import (
        DEFAULT_AVAILABILITY_DOMAIN,
        DEFAULT_IMAGE_ID,
        DEFAULT_REGION,
        DEFAULT_SUBNET_ID,
        SHAPE,
        TARGET_MEMORY_GB,
        TARGET_OCPUS,
    )

    values = dict(os.environ if env is None else env)
    region = values.get("OCI_REGION", "").strip() or DEFAULT_REGION
    subnet_id = values.get("OCI_SUBNET_ID", "").strip() or DEFAULT_SUBNET_ID
    image_id = values.get("OCI_IMAGE_ID", "").strip() or DEFAULT_IMAGE_ID
    availability_domain = (
        values.get("OCI_AVAILABILITY_DOMAIN", "").strip()
        or DEFAULT_AVAILABILITY_DOMAIN
    )

    try:
        if oci_module is None:
            import oci as oci_module

        signer = signer or oci_module.auth.signers.InstancePrincipalsSecurityTokenSigner()
        tenancy_id = str(getattr(signer, "tenancy_id", "") or "")
        if not tenancy_id:
            return 1, {
                "status": "blocked",
                "failed_check": "instance_principal_tenancy_identity",
                "diagnostic_code": "missing_tenancy_id",
            }

        compartment_id = (
            values.get("OCI_COMPARTMENT_OCID", "").strip() or tenancy_id
        )
        no_retry = oci_module.retry.NoneRetryStrategy()
        compute = compute or oci_module.core.ComputeClient(
            {"region": region},
            signer=signer,
            retry_strategy=no_retry,
            timeout=(8, 15),
        )
        network = network or oci_module.core.VirtualNetworkClient(
            {"region": region},
            signer=signer,
            retry_strategy=no_retry,
            timeout=(8, 15),
        )

        # OCI ListInstances only lists one compartment at a time. Check
        # both the tenancy root and target compartment to reduce duplicate risk.
        inventory_compartments = [tenancy_id]
        if compartment_id != tenancy_id:
            inventory_compartments.append(compartment_id)
        for inventory_compartment in inventory_compartments:
            try:
                oci_module.pagination.list_call_get_all_results(
                    compute.list_instances,
                    compartment_id=inventory_compartment,
                )
            except Exception as exc:
                return 1, {
                    "status": "blocked",
                    "failed_check": "list_instances",
                    "compartment_scope": (
                        "tenancy_root"
                        if inventory_compartment == tenancy_id
                        else "target_compartment"
                    ),
                    **sanitized_error(exc),
                }

        try:
            subnet = network.get_subnet(subnet_id).data
        except Exception as exc:
            return 1, {
                "status": "blocked",
                "failed_check": "get_configured_subnet",
                **sanitized_error(exc),
            }
        if str(getattr(subnet, "lifecycle_state", "")).upper() != "AVAILABLE":
            return 1, {
                "status": "blocked",
                "failed_check": "configured_subnet_available",
                "diagnostic_code": "subnet_not_available",
            }

        try:
            image = compute.get_image(image_id).data
        except Exception as exc:
            return 1, {
                "status": "blocked",
                "failed_check": "get_configured_image",
                **sanitized_error(exc),
            }
        if str(getattr(image, "lifecycle_state", "")).upper() != "AVAILABLE":
            return 1, {
                "status": "blocked",
                "failed_check": "configured_image_available",
                "diagnostic_code": "image_not_available",
            }

        capacity_details = oci_module.core.models.CreateComputeCapacityReportDetails(
            compartment_id=tenancy_id,
            availability_domain=availability_domain,
            shape_availabilities=[
                oci_module.core.models.CreateCapacityReportShapeAvailabilityDetails(
                    instance_shape=SHAPE,
                    instance_shape_config=(
                        oci_module.core.models.CapacityReportInstanceShapeConfig(
                            ocpus=TARGET_OCPUS,
                            memory_in_gbs=TARGET_MEMORY_GB,
                        )
                    ),
                )
            ],
        )
        try:
            report = compute.create_compute_capacity_report(capacity_details).data
        except Exception as exc:
            return 1, {
                "status": "blocked",
                "failed_check": "create_compute_capacity_report",
                **sanitized_error(exc),
            }

        rows = list(getattr(report, "shape_availabilities", []) or [])
        return 0, {
            "status": "ready",
            "region": region,
            "target": {
                "shape": SHAPE,
                "ocpus": TARGET_OCPUS,
                "memory_gb": TARGET_MEMORY_GB,
            },
            "checks": {
                "instance_inventory": "passed",
                "subnet": "available",
                "image": "available",
                "capacity_report_permission": "passed",
            },
            "capacity_rows_returned": len(rows),
            "note": (
                "Preflight does not prove launch permission or available capacity. "
                "The service still must verify OCI state after any launch request."
            ),
        }
    except Exception as exc:
        return 1, {
            "status": "blocked",
            "failed_check": "preflight_initialization",
            **sanitized_error(exc),
        }


def main() -> int:
    try:
        env = load_env_file()
    except (OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "environment_file_read_failed"
        output = {"status": "blocked", "failed_check": "environment_file", "diagnostic_code": reason}
        print(json.dumps(output, sort_keys=True))
        return 2
    code, result = run_preflight(env=env)
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
