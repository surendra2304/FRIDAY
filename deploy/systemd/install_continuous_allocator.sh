#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${EUID}" -ne 0 ]]; then echo "Run this installer as root (sudo)." >&2; exit 2; fi
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_SCRIPT="${SOURCE_ROOT}/scripts/oci_a1_continuous_allocator.py"
SOURCE_REQUIREMENTS="${SOURCE_ROOT}/requirements-oci.txt"
SOURCE_UNIT="${SOURCE_ROOT}/deploy/systemd/friday-oci-a1-allocator.service"
INSTALL_DIR="/opt/friday-oci-a1-allocator"
STATE_DIR="/var/lib/friday-oci-a1-allocator"
CONFIG_FILE="/etc/friday-oci-a1-allocator.conf"
UNIT_FILE="/etc/systemd/system/friday-oci-a1-allocator.service"

for file in "${SOURCE_SCRIPT}" "${SOURCE_REQUIREMENTS}" "${SOURCE_UNIT}"; do
  [[ -f "${file}" ]] || { echo "Required source file missing: ${file}" >&2; exit 2; }
done
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 2; }
python3 -m venv --help >/dev/null 2>&1 || {
  echo "Python venv support is missing; install python3-venv first." >&2; exit 2;
}

COMPARTMENT_ID="${OCI_COMPARTMENT_OCID:-}"
if [[ -z "${COMPARTMENT_ID}" ]] && command -v curl >/dev/null; then
  METADATA="$(curl --silent --show-error --fail --max-time 3 \
    -H 'Authorization: Bearer Oracle' http://169.254.169.254/opc/v2/instance/ 2>/dev/null || true)"
  if [[ -n "${METADATA}" ]]; then
    COMPARTMENT_ID="$(printf '%s' "${METADATA}" | python3 -c \
      'import json,sys; print(json.load(sys.stdin).get("compartmentId", ""))' 2>/dev/null || true)"
  fi
fi
if [[ ! "${COMPARTMENT_ID}" =~ ^ocid1\.(compartment|tenancy)\.oc1\. ]]; then
  echo "Could not establish a valid OCI compartment OCID. Set OCI_COMPARTMENT_OCID and retry." >&2
  exit 2
fi

if ! getent passwd friday-allocator >/dev/null; then
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin friday-allocator
fi
install -d -o root -g friday-allocator -m 0750 "${INSTALL_DIR}"
install -d -o friday-allocator -g friday-allocator -m 0750 "${STATE_DIR}"
install -o root -g friday-allocator -m 0640 "${SOURCE_SCRIPT}" "${INSTALL_DIR}/oci_a1_continuous_allocator.py"
install -o root -g friday-allocator -m 0640 "${SOURCE_REQUIREMENTS}" "${INSTALL_DIR}/requirements-oci.txt"
install -o root -g root -m 0644 "${SOURCE_UNIT}" "${UNIT_FILE}"
if [[ ! -x "${INSTALL_DIR}/.venv/bin/python" ]]; then python3 -m venv "${INSTALL_DIR}/.venv"; fi
"${INSTALL_DIR}/.venv/bin/python" -m pip install --disable-pip-version-check \
  --requirement "${INSTALL_DIR}/requirements-oci.txt"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  umask 027
  cat > "${CONFIG_FILE}" <<EOF
# Non-secret config only. Do not place API keys or tokens here.
OCI_COMPARTMENT_OCID=${COMPARTMENT_ID}
OCI_REGION=ap-hyderabad-1
OCI_AVAILABILITY_DOMAIN=qvRd:AP-HYDERABAD-1-AD-1
OCI_A1_POLL_SECONDS=120
EOF
  chmod 0640 "${CONFIG_FILE}"
  chown root:friday-allocator "${CONFIG_FILE}"
else
  EXISTING_COMPARTMENT="$(sed -n 's/^OCI_COMPARTMENT_OCID=//p' "${CONFIG_FILE}" | tail -n 1)"
  if [[ -z "${EXISTING_COMPARTMENT}" ]]; then
    printf '\nOCI_COMPARTMENT_OCID=%s\n' "${COMPARTMENT_ID}" >> "${CONFIG_FILE}"
  elif [[ ! "${EXISTING_COMPARTMENT}" =~ ^ocid1\.(compartment|tenancy)\.oc1\. ]]; then
    echo "Existing config has an invalid OCI_COMPARTMENT_OCID; refusing to overwrite it." >&2
    exit 2
  fi
  chmod 0640 "${CONFIG_FILE}"
  chown root:friday-allocator "${CONFIG_FILE}"
fi

systemctl daemon-reload
systemctl enable --now friday-oci-a1-allocator.service
sleep 2
systemctl --no-pager --full status friday-oci-a1-allocator.service || true
echo "Recent allocator logs:"
journalctl -u friday-oci-a1-allocator.service -n 30 --no-pager || true
