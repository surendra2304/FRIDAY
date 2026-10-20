#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ROOT="/opt/friday-arm-sniper"
APP_ROOT="${INSTALL_ROOT}/app"
SERVICE_USER="friday-arm-sniper"
SERVICE_GROUP="friday-arm-sniper"
SERVICE_NAME="friday-oci-a1-allocator.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this installer with sudo/root." >&2
  exit 2
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemd is required to keep the allocator alive across process/VM restarts." >&2
  exit 2
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -o root -g root -m 0755 "${INSTALL_ROOT}" "${APP_ROOT}" "${APP_ROOT}/scripts"
install -m 0644 "${REPO_ROOT}/scripts/oci_a1_sniper.py" "${APP_ROOT}/scripts/oci_a1_sniper.py"
install -m 0644 "${REPO_ROOT}/scripts/oci_a1_continuous.py" "${APP_ROOT}/scripts/oci_a1_continuous.py"
install -m 0644 "${REPO_ROOT}/scripts/__init__.py" "${APP_ROOT}/scripts/__init__.py"
install -m 0644 "${REPO_ROOT}/systemd/friday-oci-a1-allocator.service" "/etc/systemd/system/${SERVICE_NAME}"

if [[ ! -x "${INSTALL_ROOT}/venv/bin/python" ]]; then
  if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
      export DEBIAN_FRONTEND=noninteractive
      apt-get update
      apt-get install -y python3-venv
    else
      echo "Python venv/ensurepip is unavailable and apt-get is not available to install it." >&2
      exit 2
    fi
  fi
  python3 -m venv "${INSTALL_ROOT}/venv"
fi
"${INSTALL_ROOT}/venv/bin/python" -m pip install --disable-pip-version-check "oci==2.188.0"

chown -R root:root "${INSTALL_ROOT}"
chmod -R go-w "${INSTALL_ROOT}"
chmod 0755 "${INSTALL_ROOT}" "${APP_ROOT}" "${APP_ROOT}/scripts"
chmod 0644 "${APP_ROOT}/scripts/"*.py

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true

echo "Installation issued. Confirm the service log and /var/lib/friday-arm-sniper/state.json."
echo "This service uses OCI Instance Principals; it does not store an OCI private API key."
