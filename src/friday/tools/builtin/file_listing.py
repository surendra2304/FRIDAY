"""Built-in tool for listing directory files safely."""

import datetime
from pathlib import Path
from typing import Any

from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool


class FileListingTool(BaseTool):
    """Safe, read-only directory listing tool restricted to the workspace directory."""

    name = "list_dir"
    description = "List files and subdirectories within a directory relative to the workspace root. Output is limited to 100 items."
    safety_level = SafetyLevel.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path relative to the workspace root (e.g. '.' or 'src/friday')",
            }
        },
        "required": [],
    }

    def execute(self, path: str = ".", **kwargs: Any) -> ToolResult:
        workspace_root = Path.cwd().resolve()

        # Defensively reject absolute paths or drive letters directly
        path_obj = Path(path)
        if path_obj.is_absolute() or path_obj.anchor:
            return ToolResult(
                name=self.name,
                content="Security Error: Directory path is outside the allowed workspace sandbox.",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            # Combine paths and resolve
            target_path = (workspace_root / path).resolve()

            # Traversal check
            if not target_path.is_relative_to(workspace_root):
                return ToolResult(
                    name=self.name,
                    content="Security Error: Directory path is outside the allowed workspace sandbox.",
                    is_error=True,
                    safety_level=self.safety_level,
                )

            if not target_path.exists():
                return ToolResult(
                    name=self.name,
                    content=f"Error: Path '{path}' does not exist.",
                    is_error=True,
                    safety_level=self.safety_level,
                )

            if not target_path.is_dir():
                return ToolResult(
                    name=self.name,
                    content=f"Error: Path '{path}' is a file, not a directory. Use read_file to view file contents.",
                    is_error=True,
                    safety_level=self.safety_level,
                )

            items = list(target_path.iterdir())
            total_items = len(items)

            # Limit listing to first 100 items
            limit = 100
            listed_items = sorted(items, key=lambda x: (not x.is_dir(), x.name.lower()))[:limit]

            lines = [f"### Directory Listing: {path}\n"]
            lines.append(f"Total items in folder: {total_items} (showing first {len(listed_items)})")
            lines.append("| Name | Type | Size (Bytes) | Last Modified (UTC) |")
            lines.append("| --- | --- | --- | --- |")

            for item in listed_items:
                name = item.name
                is_directory = item.is_dir()
                item_type = "Directory" if is_directory else "File"

                try:
                    stat = item.stat()
                    size = "-" if is_directory else f"{stat.st_size:,}"
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc)
                    mtime_str = mtime.strftime("%Y-%m-%d %H:%M:%S UTC")
                except Exception:
                    size = "Error"
                    mtime_str = "Error"

                lines.append(f"| {name} | {item_type} | {size} | {mtime_str} |")

            if total_items > limit:
                lines.append(f"\n*(Truncated: {total_items - limit} more items not shown)*")

            return ToolResult(
                name=self.name,
                content="\n".join(lines),
                is_error=False,
                safety_level=self.safety_level,
            )

        except Exception as e:
            return ToolResult(
                name=self.name,
                content=f"Error: Unable to list directory. Details: {e!s}",
                is_error=True,
                safety_level=self.safety_level,
            )
