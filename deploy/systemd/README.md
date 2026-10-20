# Persistent OCI A1 allocator

The prior GitHub Actions workflows each made one bounded allocation attempt and exited. This service remains active on the AMD VM and retries until an A1 instance with 2 OCPUs / 12 GB RAM is confirmed RUNNING.

## Operating behavior

- Checks OCI inventory before each launch; any non-terminated A1 instance prevents duplicate allocation.
- No capacity is a normal retryable state. The worker waits 120 seconds and checks again indefinitely.
- Transient API errors use bounded exponential backoff. Explicit authorization/configuration errors stop the process instead of being disguised as capacity misses.
- Before launch, the worker persists an idempotency token and chosen fault domain. If an API response is ambiguous, the next cycle checks inventory and retries the same request/token.
- State is persisted at \`/var/lib/friday-oci-a1-allocator/state.json\`; logs are available via \`journalctl\`.
- Authentication uses OCI instance principals; do not put API private keys or tokens into the config.

## Prerequisites

1. The AMD VM must belong to a dynamic group with narrowly scoped IAM policies to read instances and capacity reports, create compute instances, and use the selected subnet/VNIC and boot-volume resources. Do not grant tenancy-wide administrator privileges.
2. Confirm the configured availability domain, subnet, and image OCIDs are valid and compatible in \`ap-hyderabad-1\`. The worker carries forward the subnet/image/public SSH-key defaults from the existing sniper; override with \`OCI_SUBNET_ID\`, \`OCI_IMAGE_ID\`, and \`OCI_SSH_PUBLIC_KEY\` if required.
3. Python venv support and outbound HTTPS to OCI endpoints and the Python package index must be available during installation.

## Install

Run from a fresh, trusted FRIDAY checkout at a tested commit. Do not use the stale \`/opt/friday_universe\` checkout.

\`\`\`bash
sudo ./deploy/systemd/install_continuous_allocator.sh
\`\`\`

The installer uses OCI instance metadata to discover the instance compartment when possible, creates a dedicated unprivileged service account, pins the OCI SDK, installs the unit and starts it. It fails closed if it cannot establish a valid compartment identifier.

Check operation:

\`\`\`bash
sudo systemctl status friday-oci-a1-allocator.service --no-pager
sudo journalctl -u friday-oci-a1-allocator.service -f
sudo cat /var/lib/friday-oci-a1-allocator/state.json
\`\`\`

An accepted launch response is not completion. The allocator stops only after a fresh OCI inventory query confirms the target shape/resources are RUNNING. Once the service exits successfully, systemd does not restart it.

The GitHub Actions capacity workflows can remain for monitoring/manual diagnostics, but they are not the primary search engine. Do not deploy the ten application services as part of the allocator rollout.
