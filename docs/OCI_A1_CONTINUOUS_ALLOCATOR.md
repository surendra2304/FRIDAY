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

## IAM bootstrap — required before installation

**Do not install/start the service until this preflight is green.** The live AMD host currently authenticates through Instance Principals, but its calls to `ListInstances`, `GetSubnet`, and `CreateComputeCapacityReport` return `404 NotAuthorizedOrNotFound`. This is an authorization/resource-visibility failure, not evidence that A1 capacity is unavailable. The host cannot grant itself IAM permissions. A tenancy administrator must complete the setup below in the OCI Console.

### Recommended least-privilege layout

1. In **Identity & Security → Compartments**, create a dedicated compute compartment named `FRIDAYArmWorkloads`. Keep the already-existing subnet in its existing network compartment. Do not grant the allocator broad `manage instance-family in tenancy` privileges.
2. In **Identity & Security → Domains → Dynamic groups**, create `FridayArmAllocator` with a matching rule that includes only the AMD VM used to run the allocator:
   ```text
   ALL {instance.id = '<AMD_VM_INSTANCE_OCID>'}
   ```
   Use the actual instance OCID from the Compute instance details page. Dynamic groups have no permissions until a policy grants them.
3. In **Identity & Security → Policies**, create a policy at the tenancy/root scope with the statements below. Replace `<NETWORK_COMPARTMENT_NAME>` with the compartment that really contains the chosen subnet; use `in tenancy` instead if that subnet is in the tenancy root. These statements deliberately scope instance creation to the dedicated compute compartment.

   ```text
   Allow dynamic-group FridayArmAllocator to read instances in tenancy
   Allow dynamic-group FridayArmAllocator to manage instances in compartment FRIDAYArmWorkloads
   Allow dynamic-group FridayArmAllocator to read instance-images in tenancy where target.image.id = 'ocid1.image.oc1.ap-hyderabad-1.aaaaaaaacx5cw6qxwnemznb2wojrfdbkuepvgwzlwzqa2snxqslops3nmlua'
   Allow dynamic-group FridayArmAllocator to read app-catalog-listing in tenancy
   Allow dynamic-group FridayArmAllocator to use volume-family in compartment FRIDAYArmWorkloads
   Allow dynamic-group FridayArmAllocator to use subnets in compartment <NETWORK_COMPARTMENT_NAME>
   Allow dynamic-group FridayArmAllocator to use vnics in compartment <NETWORK_COMPARTMENT_NAME>
   Allow dynamic-group FridayArmAllocator to use network-security-groups in compartment <NETWORK_COMPARTMENT_NAME>
   Allow dynamic-group FridayArmAllocator to manage compute-capacity-reports in tenancy
   ```

   The `read instances in tenancy` statement lets the allocator check root-compartment inventory for an existing A1 before creating one. The allocator separately lists the configured target compartment because OCI list operations are not recursive. The dedicated-compartment scope limits its instance management/launch permissions. Review the exact subnet and image OCIDs before applying this policy.

4. Create `/etc/friday-arm-sniper.env` on the AMD VM, owned by root and mode `0600`, with non-secret resource settings. Do not place API private keys or passwords in this file. At minimum set the target compartment OCID and a subnet OCID verified in the OCI Console:
   ```text
   OCI_REGION=ap-hyderabad-1
   OCI_COMPARTMENT_OCID=<FRIDAYArmWorkloads_COMPARTMENT_OCID>
   OCI_SUBNET_ID=<VERIFIED_SUBNET_OCID>
   ```
   The existing Ubuntu 24.04 image OCID defaults to an image that was verified as `AVAILABLE`; override it only if selecting a different verified image. Ensure the chosen subnet permits a public IP if the instance must be reached from the internet.

5. Re-run `sudo bash scripts/install_oci_a1_continuous.sh` from a fresh checkout of merged `main`. The installer runs a fail-closed preflight and will not enable/start systemd if instance inventory, subnet, image, or capacity-report permission checks fail. Once preflight passes, monitor the first allocator attempt for a launch-permission result. A successful capacity report does not prove launch permission or that capacity exists.

References:
- [Oracle: Dynamic-group matching rules](https://docs.oracle.com/en-us/iaas/Content/Identity/Tasks/managingdynamicgroups.htm)
- [Oracle: Core policy reference](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/corepolicyreference.htm)
- [Oracle: Compute launch policy template](https://docs.oracle.com/en-us/iaas/Content/Identity/policiescommon/commonpolicies.htm)

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

The repository checkout used for installation must be current and must not be the stale `/opt/friday_universe` deployment snapshot. The installer checks for Python venv support and, on Ubuntu/Debian, installs the matching `python3-venv` package if it is missing. Verify OCI policy permissions and the exact configured subnet, image, compartment and SSH public key before starting the service.

## Rollback

```bash
sudo systemctl disable --now friday-oci-a1-allocator.service
```

Rollback stops the background search. Do not delete an existing instance as part of rollback; instance deletion is a separate, destructive decision.
