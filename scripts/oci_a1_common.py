"""Shared constants and pure helpers for OCI A1 allocation."""
from __future__ import annotations

from typing import Any

SHAPE = "VM.Standard.A1.Flex"
TARGET_DISPLAY_NAME = "FRIDAY Universe ARM"
TARGET_OCPUS = 2
TARGET_MEMORY_GB = 12
BOOT_VOLUME_GB = 50
DEFAULT_REGION = "ap-hyderabad-1"
DEFAULT_AVAILABILITY_DOMAIN = "qvRd:AP-HYDERABAD-1-AD-1"
# Non-secret resource identifiers retained from the prior allocator configuration.
DEFAULT_SUBNET_ID = "ocid1.subnet.oc1.ap-hyderabad-1.aaaaaaaa2rox2pqtptjmmm6p6ddritbf6uxxa7zpeiicxwx6kbsydcfudibq"
DEFAULT_IMAGE_ID = "ocid1.image.oc1.ap-hyderabad-1.aaaaaaaacx5cw6qxwnemznb2wojrfdbkuepvgwzlwzqa2snxqslops3nmlua"
DEFAULT_SSH_PUBLIC_KEY = (
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDsKkIMQ/GEBLSdYRPkvO6k1f8PJF/Xeva6qbEz2aUmE9DzWAg473x+tyH3iwSxYsg6j/jw/KZvnj8cqlSWYPq+93H88gyi5+etoXmL3Ej4bpQalSboL91HOqiVgeXtzx4XKtuizmY+w6osOlJJQiW0nFiHyeKzDFWfE02P4ljvIku7Fe3O2tu531qzzLBjzDWHWS9LRb5TvQ9f3rHZSnCXs4RiAXSj1fEyjjMOFcIzyfyqeORMM/3816Vv4eQ6/6hrx7V127s8f+14JKQJfykQryDdcOvKjLons+wm61/yMKbQgFASIHHTIPVE3ZRedkEQP1Q80BWh15wm9USmMkgP ssh-key-2026-10-13"
)


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


def available_capacity(entries: list[Any], lane: str = "primary") -> list[Any]:
    """Return available positive/unspecified capacity, ordered by fault domain."""
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
