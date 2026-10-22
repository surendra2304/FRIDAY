"""Path policy for generated Python tools.

Generated capabilities are importable modules, not arbitrary files. Keep the
candidate and the eventual installation inside the one builtin-tool directory,
and reject ambiguous or traversing names before any reviewer or applier sees them.
"""

from __future__ import annotations

import keyword
from pathlib import Path, PureWindowsPath

TOOL_MODULE_DIRECTORY = "src/friday/tools/builtin"


class ToolPathError(ValueError):
    """A requested generated-tool path is not a safe builtin module path."""


def resolve_tool_module_path(
    repository_root: str | Path,
    target_path: str = "",
    *,
    tool_name: str = "",
) -> tuple[str, Path]:
    """Return a normalized repo-relative path and its resolved destination.

    ``target_path`` is always repository-relative and must name a direct Python
    module in ``src/friday/tools/builtin``. The default is derived from
    ``tool_name``. Symlinks, Windows-style paths, traversal, and non-module names
    are refused so both generation and installation agree on the file being
    reviewed.
    """
    root = Path(repository_root).resolve()
    tool_root = (root / TOOL_MODULE_DIRECTORY).resolve()
    try:
        tool_root.relative_to(root)
    except ValueError as exc:
        raise ToolPathError("the builtin-tools directory resolves outside the repository") from exc

    raw = str(target_path or "").strip()
    if not raw:
        if not tool_name:
            raise ToolPathError("a tool name or target path is required")
        raw = f"{TOOL_MODULE_DIRECTORY}/{tool_name}.py"

    if "\x00" in raw:
        raise ToolPathError("NUL bytes are not allowed in a tool path")
    candidate_relative = Path(raw)
    windows_path = PureWindowsPath(raw)
    if candidate_relative.is_absolute() or windows_path.drive or "\\" in raw:
        raise ToolPathError("target_path must be a repository-relative path using '/' separators")
    if ".." in candidate_relative.parts:
        raise ToolPathError("parent-directory traversal is not allowed in target_path")
    if candidate_relative.suffix != ".py":
        raise ToolPathError("a generated tool path must end in '.py'")

    stem = candidate_relative.stem
    if not stem.isidentifier() or keyword.iskeyword(stem):
        raise ToolPathError("the tool filename must be a valid Python module name")
    if target_path and tool_name and stem != tool_name:
        raise ToolPathError("the tool name must match the target filename")

    unresolved = root / candidate_relative
    # A symlink anywhere in the selected path makes the reviewed path differ from
    # the file that a later write could reach. Refuse rather than follow it.
    cursor = root
    for part in candidate_relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ToolPathError("symlinks are not allowed in generated-tool paths")

    try:
        destination = unresolved.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolPathError(f"target_path could not be resolved: {exc}") from exc

    if destination.parent != tool_root:
        raise ToolPathError(
            f"generated tools must be direct modules in {TOOL_MODULE_DIRECTORY}/"
        )

    relative = destination.relative_to(root).as_posix()
    return relative, destination
