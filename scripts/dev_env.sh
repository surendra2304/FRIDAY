#!/usr/bin/env bash
# ==============================================================================
# Build a complete FRIDAY development environment.
#
# Why this exists: `pip install -e ".[dev]"` cannot complete on a Linux host
# without the CPython headers, because `resemblyzer` (voice biometrics) pulls in
# `webrtcvad`, whose sdist compiles a C extension against `Python.h`. CI's
# `ubuntu-latest` image happens to ship those headers, so the failure is invisible
# there and immediate everywhere else. See the Phase 0-2 truth audit, BUG-009.
#
# This script installs everything the project actually needs, minus the two
# platform-bound packages, then installs FRIDAY itself with --no-deps:
#   * resemblyzer  -> voice biometrics only, lazily imported on first use
#   * pycaw/pywinauto (win32-only, already marker-gated in pyproject.toml)
#
# Everything the test suite, linters and the API server need is installed.
#
# Usage:  bash scripts/dev_env.sh [venv_path]     (default: /home/user/.venv)
# ==============================================================================
set -o errexit
set -o pipefail

VENV="${1:-/home/user/.venv}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Creating virtualenv at ${VENV}"
python3 -m venv "${VENV}"
PY="${VENV}/bin/python"

echo "==> Upgrading pip"
"${PY}" -m pip install --quiet --upgrade pip

echo "==> Resolving dependency list from pyproject.toml"
DEPS_FILE="$(mktemp)"
"${PY}" - "${REPO_ROOT}/pyproject.toml" > "${DEPS_FILE}" <<'PY'
import sys, tomllib

with open(sys.argv[1], "rb") as handle:
    project = tomllib.load(handle)["project"]

# Platform-bound or header-bound packages that block a clean Linux install.
SKIP_SUBSTRINGS = ("resemblyzer",)

for requirement in project["dependencies"]:
    if any(skip in requirement for skip in SKIP_SUBSTRINGS):
        continue
    # Windows-only markers are already correct in pyproject.toml; pip evaluates them.
    print(requirement)

for requirement in project["optional-dependencies"]["dev"]:
    print(requirement)
for requirement in project["optional-dependencies"]["browser"]:
    print(requirement)
PY

echo "==> Installing $(wc -l < "${DEPS_FILE}") dependencies"
"${PY}" -m pip install --quiet --requirement "${DEPS_FILE}"
rm -f "${DEPS_FILE}"

echo "==> Installing FRIDAY (editable, without the header-bound extras)"
"${PY}" -m pip install --quiet --editable "${REPO_ROOT}" --no-deps

echo "==> Verifying"
"${PY}" -c "import friday, friday_deep; print('friday', friday.__file__)"
"${PY}" -m pytest --version
"${PY}" -m ruff --version

cat <<EOF

==> Environment ready: ${PY}
    Run the suite:   ${VENV}/bin/python -m pytest -m "not live and not hardware and not windows" -q
    Boot the server: ${VENV}/bin/python -m uvicorn friday.api.server:app --host 0.0.0.0 --port 8811
EOF
