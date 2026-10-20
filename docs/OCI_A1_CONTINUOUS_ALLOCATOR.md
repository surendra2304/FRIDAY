# Continuous OCI Ampere A1 allocator

## Required behavior

The production search mechanism is a persistent `systemd` service on the always-on FRIDAY Universe AMD VM. It checks for an existing `VM.Standard.A1.Flex` instance, requests capacity for 2 OCPUs / 12 GB RAM / 50 GB boot, and retries until the target instance is `RUNNING`. A GitHub Actions run is not the allocator's uptime mechanism.

The former primary and fallback workflow schedules are removed to prevent duplicate allocation attempts. There is one persistent service rather than two staggered short-lived workers.

## Authentication and safety

- Use OCI Instance Principals from the running AMD VM; do not copy or store long-lived OCI API private keys on the host.
- The OCI dynamic group and policy must permit the instance principal to inspect the necessary compute/network resources, request capacity, and launch an instance in the configured compartment. An authorization failure is logged as a sanitized diagnostic and retried with a slower interval; it is not misreported as unavailable capacity.
- Region defaults to `ap-hyderabad-1`; availability domain, subnet, image, and SSH public key default to the existing allocator configuration and may be overridden by `/etc/friday-arm-sniper.env`. Keep that optional file root-owned and mode `0600`; it must not contain private keys or secret material.
- The allocator checks inventory before each launch, treats provisioning instances as already present, uses a stable idempotency token per target/fault-domain request, and never launches a second A1 instance if one already exists.
- A pre-existing A1 instance below target size is a manual-review condition, not permission to launch a duplicate.
- The service exits successfully only when the requested instance is observed in the `RUNNING` lifecycle state. Instance request acceptance alone is not success.

## Retry and observability

No-capacity retries occur every 60 seconds. A provisioning instance is rechecked every 20 seconds. Transient API errors retry after 120 seconds, rate limits after 180 seconds, and authorization/configuration faults after 300 seconds. The process retries indefinitely unless the target is running or an operator stops it.

Logs go to the system journal; the latest non-secret status is atomically written to `/var/lib/friday-arm-sniper/state.json`. The service uses `Restart=on-failure`, so systemd restarts it after crashes/reboots without creating a restart loop after successful allocation.

## Install / verify

From a clean, current FRIDAY repository checkout on the AMD VM:

```bash
sudo bash scripts/install_oci_a1_continuous.sh
sudo systemctl status friday-oci-a1-allocator.service --no-pager
sudo journalctl -u friday-oci-a1-allocator.service -f
sudo cat /var/lib/friday-arm-sniper/state.json
```

The repository checkout used for installation must be current and must not be the stale `/opt/friday_universe` deployment snapshot. Verify OCI policy permissions and the exact configured subnet, image, compartment and SSH public key before starting the service.

## Rollback

```bash
sudo systemctl disable --now friday-oci-a1-allocator.service
```

Rollback stops the background search. Do not delete an existing instance as part of rollback; instance deletion is a separate, destructive decision.
