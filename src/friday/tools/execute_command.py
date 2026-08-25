"""execute_command: Run a safe read-only terminal command.

Allowed commands: chcp, dir, driverquery, echo, findstr, getmac, hostname,
ipconfig, netstat, ping, systeminfo, tasklist, tree, type, ver, vol, where, whoami,
and python (temporarily for self-upgrade).
"""

import subprocess
import shlex
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

ALLOWED_COMMANDS = {
    "chcp", "dir", "driverquery", "echo", "findstr", "getmac", "hostname",
    "ipconfig", "netstat", "ping", "systeminfo", "tasklist", "tree", "type",
    "ver", "vol", "where", "whoami", "python"
}


def execute_command(command: str) -> Dict[str, Any]:
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
            check=True
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        logger.error(f"Command failed: {e}")
        return {"error": str(e)}