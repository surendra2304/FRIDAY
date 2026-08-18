"""Built-in tool for reading file contents safely."""

import os
from pathlib import Path
from typing import Any, Dict
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool


class FileReaderTool(BaseTool):
    """Safe, read-only file reading tool restricted to the workspace directory."""

    name = "read_file"
    description = "Read the contents of a text file within the workspace safely. Path must be relative to the workspace root."
    safety_level = SafetyLevel.SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (relative to the workspace root, e.g. 'README.md' or 'src/friday/main.py')",
            },
            "max_bytes": {
                "type": "integer",
                "description": "Maximum number of bytes to read (default is 102400, maximum is 524288 to prevent context flooding)",
            },
        },
        "required": ["path"],
    }

    def execute(self, path: str, max_bytes: int = 102400, **kwargs: Any) -> ToolResult:
        # Define sandbox workspace root (current working directory)
        workspace_root = Path.cwd().resolve()

        # Guard max bytes
        max_bytes = min(max(1, max_bytes), 524288)

        # Defensively reject absolute paths or drive letters directly
        path_obj = Path(path)
        if path_obj.is_absolute() or path_obj.anchor:
            return ToolResult(
                name=self.name,
                content="Security Error: File path is outside the allowed workspace sandbox.",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            # Combine paths and resolve to eliminate traversal components (e.g. '..')
            target_path = (workspace_root / path).resolve()

            # Traversal check: Target must be strictly within the workspace root
            if not target_path.is_relative_to(workspace_root):
                return ToolResult(
                    name=self.name,
                    content="Security Error: File path is outside the allowed workspace sandbox.",
                    is_error=True,
                    safety_level=self.safety_level,
                )

            if not target_path.is_file():
                return ToolResult(
                    name=self.name,
                    content=f"Error: Path '{path}' is not a file or does not exist.",
                    is_error=True,
                    safety_level=self.safety_level,
                )

            # Check file size before reading to avoid memory blowout
            file_size = target_path.stat().st_size
            if file_size == 0:
                return ToolResult(
                    name=self.name,
                    content="File is empty.",
                    is_error=False,
                    safety_level=self.safety_level,
                )

            # Binary file check
            # Read first 1024 bytes and check for null bytes
            with open(target_path, "rb") as f:
                chunk = f.read(1024)
                if b"\x00" in chunk:
                    return ToolResult(
                        name=self.name,
                        content=f"Error: File '{path}' appears to be a binary file. Reading binary files is not supported to protect context sanity.",
                        is_error=True,
                        safety_level=self.safety_level,
                    )

            # Read text with proper encoding handling
            # Try UTF-8 first, fallback to latin-1
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    content = f.read(max_bytes + 1)
            except UnicodeDecodeError:
                with open(target_path, "r", encoding="latin-1") as f:
                    content = f.read(max_bytes + 1)

            truncated = len(content) > max_bytes
            display_content = content[:max_bytes]

            summary = f"### File Content: {path}\n"
            if truncated:
                summary += f"*(Showing first {max_bytes} bytes of {file_size} total bytes)*\n\n"
            else:
                summary += f"*(Read complete: {len(display_content)} bytes)*\n\n"

            summary += f"```\n{display_content}\n```"
            if truncated:
                summary += "\n\n*(Truncated due to size limit)*"

            return ToolResult(
                name=self.name,
                content=summary,
                is_error=False,
                safety_level=self.safety_level,
            )

        except Exception as e:
            return ToolResult(
                name=self.name,
                content=f"Error: Unable to read file. Details: {str(e)}",
                is_error=True,
                safety_level=self.safety_level,
            )
