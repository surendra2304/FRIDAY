# -*- coding: utf-8 -*-
"""Filesystem and terminal tools with strict safety gating.

file_operations: read/write/append/list/move are SAFE user-directed actions;
delete is refused here and requires the SENSITIVE text-mode authorization path.
execute_command: a strict ALLOWLIST of read-only diagnostic commands plus a
hard block on destructive patterns — arbitrary command execution is not
exposed through the SAFE tool surface.
"""

import shutil
from pathlib import Path
from typing import Any, List

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.file_and_command")

_MAX_READ_CHARS = 8000


class FileOperationsTool(BaseTool):
    """Read, write, append, list, or move files. Delete requires SENSITIVE authorization."""

    name = "file_operations"
    description = (
        "Filesystem operations. Actions: 'read' (file text), 'write' (create/overwrite "
        "with content), 'append' (add content to the end), 'list' (directory entries), "
        "'move' (move to destination path). 'delete' is a destructive action refused by "
        "this tool and requires explicit text-mode SENSITIVE authorization."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file/directory path."},
            "action": {"type": "string", "enum": ["read", "write", "append", "list", "move", "delete"],
                       "description": "File operation."},
            "content": {"type": "string", "description": "Text content (for write/append)."},
            "destination": {"type": "string", "description": "Destination path (for move)."},
        },
        "required": ["path", "action"],
    }

    def execute(self, path: str = "", action: str = "", content: str = "",
                destination: str = "", **kwargs: Any) -> ToolResult:
        act = (action or "").strip().lower()
        if not path:
            return ToolResult(name=self.name, content="No path provided.", is_error=True,
                              safety_level=self.safety_level)

        if act == "delete":
            return ToolResult(
                name=self.name,
                content=("Deleting files is a destructive action refused by this tool. "
                         "It requires explicit SENSITIVE text-mode authorization."),
                is_error=True, safety_level=self.safety_level,
            )

        p = Path(path).expanduser()
        try:
            if act == "read":
                if not p.is_file():
                    return ToolResult(name=self.name, content=f"File not found: {p}", is_error=True,
                                      safety_level=self.safety_level)
                text = p.read_text(encoding="utf-8", errors="replace")
                trimmed = text[:_MAX_READ_CHARS] + ("... [truncated]" if len(text) > _MAX_READ_CHARS else "")
                return ToolResult(name=self.name, content=trimmed, is_error=False,
                                  safety_level=self.safety_level)

            if act in ("write", "append"):
                if not content:
                    return ToolResult(name=self.name, content=f"action='{act}' requires content.",
                                      is_error=True, safety_level=self.safety_level)
                p.parent.mkdir(parents=True, exist_ok=True)
                if act == "write":
                    p.write_text(content, encoding="utf-8")
                else:
                    with open(p, "a", encoding="utf-8") as f:
                        f.write(content)
                return ToolResult(name=self.name, content=f"{act.capitalize()} {len(content)} chars to {p}.",
                                  is_error=False, safety_level=self.safety_level)

            if act == "list":
                if not p.is_dir():
                    return ToolResult(name=self.name, content=f"Directory not found: {p}", is_error=True,
                                      safety_level=self.safety_level)
                entries: List[str] = [f"{e.name}{'' if e.is_dir() else ''}" for e in p.iterdir()]
                listing = "\n".join(sorted(entries)[:200]) or "(empty directory)"
                return ToolResult(name=self.name, content=listing, is_error=False,
                                  safety_level=self.safety_level)

            if act == "move":
                if not destination:
                    return ToolResult(name=self.name, content="action='move' requires destination.",
                                      is_error=True, safety_level=self.safety_level)
                if not p.exists():
                    return ToolResult(name=self.name, content=f"Not found: {p}", is_error=True,
                                      safety_level=self.safety_level)
                dest = Path(destination).expanduser()
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(dest))
                return ToolResult(name=self.name, content=f"Moved {p} -> {dest}.", is_error=False,
                                  safety_level=self.safety_level)

            return ToolResult(name=self.name, content=f"Unknown action '{act}'.", is_error=True,
                              safety_level=self.safety_level)
        except Exception as e:
            return ToolResult(name=self.name, content=f"File operation failed: {e}",
                              is_error=True, safety_level=self.safety_level)


# ---------------------------------------------------------------------------
# Terminal command execution — strict allowlist
# ---------------------------------------------------------------------------

# Read-only diagnostic commands FRIDAY may execute directly
_ALLOWED_COMMANDS = {
    "ping", "ipconfig", "whoami", "systeminfo", "tasklist", "netstat",
    "hostname", "ver", "dir", "echo", "where", "tree", "type", "findstr",
    "getmac", "driverquery", "vol", "chcp",
}

# Substrings that must never appear in an executed command (defense in depth:
# even allowlisted binaries cannot carry destructive arguments/pipes)
_FORBIDDEN_PATTERNS = (
    "format", " del ", "del ", "rmdir", "rd ", "erase", "shutdown", "restart",
    "reg ", "regedit", "diskpart", "cipher", "mklink", ">", "|", "&", ";",
    "remove-item", "rm ", "mv ", "chmod", "chown", "sudo", "curl", "wget",
    "powershell", "cmd ", "bash", "eval", "invoke", "script",
)


class ExecuteCommandTool(BaseTool):
    """Execute a SAFE, allowlisted terminal command and return its output."""

    name = "execute_command"
    description = (
        "Run a safe read-only terminal command (e.g. 'ping google.com', 'ipconfig', "
        "'tasklist', 'systeminfo') and return its output. Only allowlisted diagnostic "
        "commands are permitted; destructive commands and shell redirection are blocked."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command line to execute."},
        },
        "required": ["command"],
    }

    def execute(self, command: str = "", **kwargs: Any) -> ToolResult:
        import subprocess

        cmd = (command or "").strip()
        if not cmd:
            return ToolResult(name=self.name, content="No command provided.", is_error=True,
                              safety_level=self.safety_level)

        lowered = f" {cmd.lower()} "
        program = cmd.split()[0].lower().rstrip(".exe")

        if program not in _ALLOWED_COMMANDS:
            return ToolResult(
                name=self.name,
                content=(f"Command '{program}' is not in the safe allowlist. "
                         f"Allowed: {', '.join(sorted(_ALLOWED_COMMANDS))}."),
                is_error=True, safety_level=self.safety_level,
            )
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern in lowered:
                return ToolResult(
                    name=self.name,
                    content=f"Command rejected: forbidden pattern '{pattern.strip()}' detected.",
                    is_error=True, safety_level=self.safety_level,
                )

        try:
            completed = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            output = (completed.stdout or "") + (("\n[stderr] " + completed.stderr) if completed.stderr else "")
            trimmed = output[:_MAX_READ_CHARS] + ("... [truncated]" if len(output) > _MAX_READ_CHARS else "")
            return ToolResult(name=self.name, content=trimmed or "(no output)", is_error=False,
                              safety_level=self.safety_level)
        except subprocess.TimeoutExpired:
            return ToolResult(name=self.name, content="Command timed out after 30s.", is_error=True,
                              safety_level=self.safety_level)
        except Exception as e:
            return ToolResult(name=self.name, content=f"Command failed: {e}", is_error=True,
                              safety_level=self.safety_level)
