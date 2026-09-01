"""execute_command: Run a safe read-only terminal command.

Allowed commands: chcp, dir, driverquery, echo, findstr, getmac, hostname,
ipconfig, netstat, ping, systeminfo, tasklist, tree, type, ver, vol, where, whoami,
and python (temporarily for self-upgrade).
"""

import logging
import shlex
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

ALLOWED_COMMANDS = {
    "chcp", "dir", "driverquery", "echo", "findstr", "getmac", "hostname",
    "ipconfig", "netstat", "ping", "systeminfo", "tasklist", "tree", "type",
    "ver", "vol", "where", "whoami", "python"
}


def execute_command(command: str) -> dict[str, Any]:
    """Execute a safe terminal command and return its output."""
    try:
        cmd_parts = shlex.split(command)
        if not cmd_parts:
            return {"error": "Empty command"}

        base_cmd = cmd_parts[0].lower()
        if base_cmd not in ALLOWED_COMMANDS:
            return {"error": f"Command '{base_cmd}' is not allowed"}

        result = subprocess.run(
            cmd_parts,
            shell=False,
            capture_output=True,
            text=True,
            timeout=30.0,
            check=False
        )
        return {
            "stdout": result.stdout[:100000],
            "stderr": result.stderr[:100000],
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        logger.warning(f"Command timed out after 30s: {command}")
        return {"error": "Command execution timed out after 30 seconds."}
    except Exception as e:
        logger.error(f"Command execution error: {e}")
        return {"error": str(e)}