"""One traversal policy for every tool that touches the filesystem.

Why this module exists
----------------------
The file tools disagreed with each other about what they were allowed to
touch.  ``read_file`` and ``list_dir`` resolved every path against the
process working directory and refused absolute paths and traversal;
``file_operations``, ``write_code_file`` and ``replace_file_content`` took
any path they were handed.  The result was inverted from the safety story:
reading was jailed and writing was not, so a request such as "write a note
into my project, then read it back" succeeded at step one and was refused at
step two, while a relative ``../`` traversal in the write path created files
outside the workspace without any tool objecting.

Two consequences are worth naming because they are the reason this is a
module and not a patch:

* The model treats these tools as interchangeable.  A policy that differs
  per tool is not a policy, it is a coin flip decided by which tool the
  model happened to pick.
* Writing had no self-modification guard at all.  The signed-mandate system
  in :mod:`friday.cognition.mandate` governs the self-repair pipeline, but
  ``write_code_file`` could rewrite the same files with no mandate, no
  capability and no signature.

Defaults are therefore closed:

* allowed roots are the process working directory, plus anything the
  operator lists in ``FRIDAY_WORKSPACE_ROOTS``;
* absolute paths are accepted *inside* those roots -- a user who names a
  file explicitly should not be refused merely because the absolute form
  was used -- and refused outside them;
* ``..`` traversal that resolves outside every root is refused;
* sensitive names, suffixes and directories are refused for reads *and*
  writes, so a write can no longer create the ``.env`` that a read refuses
  to open;
* writes into FRIDAY's own package tree are refused unless the operator
  sets ``FRIDAY_ALLOW_SELF_MODIFICATION=true``.  The supported route to
  changing FRIDAY's source is the signed mandate, not a tool call.
"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Iterable, Sequence

__all__ = ["PathPolicyError", "WorkspacePolicy"]


class PathPolicyError(PermissionError):
    """Raised when a path is outside the policy's allowed surface.

    Subclasses :class:`PermissionError` so callers that catch broad OS-level
    permission failures keep working, while callers that want to distinguish
    "the policy refused this" from "the filesystem refused this" can catch
    this type specifically.
    """


#: Paths whose *name* alone is enough to refuse the operation.  These are the
#: files that hold credentials; a tool should not be able to read them, and a
#: write should not be able to create or clobber them either.
BLOCKED_NAMES: frozenset[str] = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".git-credentials",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "credentials",
        "master.key",
    }
)

#: Suffixes that mark key material, credential stores and database files.
BLOCKED_SUFFIXES: tuple[str, ...] = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".crt",
    ".kdbx",
)

#: Directories that hold credentials or version-control internals.  ``.git``
#: is included deliberately: writing into it can rewrite history, and no
#: ordinary user task needs it.
BLOCKED_DIRS: frozenset[str] = frozenset(
    {".git", ".ssh", ".gnupg", ".aws", ".azure", ".config"}
)


class WorkspacePolicy:
    """Resolve and police filesystem paths for FRIDAY's tools.

    A single instance is built from settings and shared, so that every tool
    answers the same question the same way.  The primary root is the process
    working directory; additional roots come from the operator.
    """

    def __init__(
        self,
        roots: Iterable[str | Path] | None = None,
        *,
        allow_self_modification: bool = False,
        protected_roots: Iterable[str | Path] | None = None,
        blocked_names: Iterable[str] | None = None,
        blocked_suffixes: Sequence[str] | None = None,
        blocked_dirs: Iterable[str] | None = None,
        include_defaults: bool = True,
    ) -> None:
        resolved: list[Path] = list(_default_roots()) if include_defaults else []
        for raw in roots or ():
            try:
                candidate = Path(os.path.expanduser(str(raw))).resolve()
            except (OSError, RuntimeError):
                # An unresolvable root is a configuration mistake, not a
                # reason to refuse every request.  Skip it and keep the
                # remaining roots; ``describe()`` shows what is in force.
                continue
            if candidate not in resolved:
                resolved.append(candidate)
        self.roots: tuple[Path, ...] = tuple(resolved)
        self.allow_self_modification = bool(allow_self_modification)

        protected: list[Path] = []
        for raw in protected_roots if protected_roots is not None else _default_protected_roots():
            try:
                protected.append(Path(os.path.expanduser(str(raw))).resolve())
            except (OSError, RuntimeError):
                continue
        self.protected_roots: tuple[Path, ...] = tuple(protected)

        self.blocked_names = frozenset(blocked_names or BLOCKED_NAMES)
        self.blocked_suffixes = tuple(blocked_suffixes or BLOCKED_SUFFIXES)
        self.blocked_dirs = frozenset(blocked_dirs or BLOCKED_DIRS)

    # ------------------------------------------------------------------
    # construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_settings(cls, settings=None) -> "WorkspacePolicy":
        """Build the policy the running configuration describes."""
        if settings is None:
            from friday.core.config import get_settings

            settings = get_settings()
        extra: list[str] = []
        raw = getattr(settings, "workspace_roots", "") or ""
        if isinstance(raw, str):
            extra = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
        elif isinstance(raw, (list, tuple)):
            extra = [str(part).strip() for part in raw if str(part).strip()]
        return cls(
            roots=extra,
            allow_self_modification=bool(getattr(settings, "allow_self_modification", False)),
        )

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------
    @property
    def base(self) -> Path:
        """The root relative paths are resolved against: where we are *now*.

        This used to be ``self.roots[0]``, captured when the policy was first
        built. FRIDAY is long-lived - a voice session, an API server and the
        autonomous loop all share one process - and anything that changes the
        working directory (a `cd` tool, a test, a restart from another folder,
        a scheduler) left every file tool resolving relative paths against a
        directory the process had left. The failures went both ways: a file the
        user could see was refused, and a relative write landed in the *old*
        workspace without a word. The live directory is what "the workspace"
        means, so it is read at call time.
        """
        try:
            return Path.cwd().resolve()
        except (OSError, RuntimeError):  # pragma: no cover - deleted cwd
            return self.roots[0]

    def effective_roots(self) -> tuple[Path, ...]:
        """Configured roots plus the live working directory, de-duplicated."""
        live = self.base
        roots: list[Path] = [live]
        for root in self.roots:
            if root not in roots:
                roots.append(root)
        return tuple(roots)

    def describe(self) -> str:
        """Human-readable summary, for error messages and diagnostics."""
        roots = ", ".join(str(r) for r in self.effective_roots())
        return (
            f"allowed roots: {roots}"
            + (
                ""
                if self.allow_self_modification
                else f"; self-modification allowed: no (protected: {', '.join(str(p) for p in self.protected_roots)})"
            )
        )

    # ------------------------------------------------------------------
    # the policy itself
    # ------------------------------------------------------------------
    def resolve(
        self,
        path: str | Path,
        *,
        for_write: bool = False,
        must_exist: bool = False,
        label: str = "path",
    ) -> Path:
        """Resolve *path* and return it, or raise :class:`PathPolicyError`.

        ``for_write`` enables the self-modification guard and the
        "sensitive file" guard in write mode.  ``must_exist`` rejects
        targets that are not already present.
        """
        text = str(path or "").strip()
        if not text:
            raise PathPolicyError(f"Refused: no {label} was provided.")

        # Paths spelled for the *other* platform must be refused, not silently
        # reinterpreted. On POSIX, ``C:\Windows\system32`` looks like a
        # relative name containing a colon and would be created inside the
        # workspace; on Windows, ``/etc/passwd`` is drive-relative and
        # resolves against whatever drive happens to be current, which is a
        # well-known way out of a workspace.
        #
        # Note that ``PureWindowsPath('/tmp/x').root`` is ``'\\'`` even on
        # POSIX, so testing ``.root`` alone would refuse every legitimate
        # POSIX absolute path - the bug that made read_file reject the
        # absolute form of a file it had just been handed.
        win = PureWindowsPath(text)
        if os.name == "nt":
            if win.root and not win.drive and not text.startswith("\\\\"):
                raise PathPolicyError(
                    f"Refused: drive-relative {label} '{text}' is ambiguous on Windows. "
                    f"Use a drive-qualified or workspace-relative path."
                )
        elif win.drive or text.startswith("\\"):
            raise PathPolicyError(
                f"Refused: Windows-style absolute {label} '{text}' is not addressable on this host."
            )

        expanded = Path(os.path.expanduser(text))
        candidate = expanded if expanded.is_absolute() else self.base / expanded
        try:
            target = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise PathPolicyError(f"Refused: {label} '{text}' could not be resolved ({exc}).") from exc

        root = self._matching_root(target)
        if root is None:
            raise PathPolicyError(
                f"Refused: {label} '{text}' resolves to '{target}', which is outside every allowed "
                f"workspace root. {self.describe()}"
            )

        self._check_sensitive(target, root, label=label)
        if for_write:
            self._check_self_modification(target, label=label)
        if must_exist and not target.exists():
            raise PathPolicyError(f"Refused: {label} '{text}' does not exist.")
        return target

    def _matching_root(self, target: Path) -> Path | None:
        for root in self.effective_roots():
            if target == root or root in target.parents:
                return root
        return None

    def _check_sensitive(self, target: Path, root: Path, *, label: str) -> None:
        name = target.name.lower()
        if name in self.blocked_names:
            raise PathPolicyError(f"Refused: '{target.name}' is a credentials file ({label}).")
        lowered = str(target).lower()
        for suffix in self.blocked_suffixes:
            if lowered.endswith(suffix):
                raise PathPolicyError(
                    f"Refused: '{target.name}' has a protected suffix '{suffix}' ({label})."
                )
        if target != root:
            try:
                parts = [part.lower() for part in target.relative_to(root).parts]
            except ValueError:
                parts = []
            for part in parts:
                if part in self.blocked_dirs:
                    raise PathPolicyError(
                        f"Refused: '{part}/' is a protected directory ({label})."
                    )

    def _check_self_modification(self, target: Path, *, label: str) -> None:
        if self.allow_self_modification:
            return
        for protected in self.protected_roots:
            if target == protected or protected in target.parents:
                from friday.core.config import find_project_root

                raise PathPolicyError(
                    f"Refused: '{target}' is inside FRIDAY's own source tree "
                    f"({protected}). Self-modification is disabled. Use the signed self-repair "
                    f"mandate, or set FRIDAY_ALLOW_SELF_MODIFICATION=true if you really mean to "
                    f"let a tool call edit the running program ({label}; project root {find_project_root()})."
                )

    # ------------------------------------------------------------------
    # convenience wrappers used by the tools
    # ------------------------------------------------------------------
    def resolve_for_read(self, path: str | Path, *, must_exist: bool = True, label: str = "path") -> Path:
        return self.resolve(path, for_write=False, must_exist=must_exist, label=label)

    def resolve_for_write(self, path: str | Path, *, label: str = "path") -> Path:
        return self.resolve(path, for_write=True, must_exist=False, label=label)


def _default_roots() -> tuple[Path, ...]:
    """Roots that are always reachable, before the operator adds any.

    The working directory is the workspace proper.  The system temporary
    directory is included because "write this to a scratch file" is an
    ordinary request and refusing it would push users towards widening the
    roots to something far more dangerous than ``/tmp``.
    """
    roots: list[Path] = [Path.cwd().resolve()]
    try:
        import tempfile

        tmp = Path(tempfile.gettempdir()).resolve()
        if tmp not in roots:
            roots.append(tmp)
    except Exception:  # pragma: no cover - defensive
        pass
    return tuple(roots)


def _default_protected_roots() -> tuple[Path, ...]:
    """FRIDAY's own shipped source, which tools may not rewrite by default."""
    protected: list[Path] = []
    try:
        import friday as _friday

        protected.append(Path(_friday.__file__).resolve().parent)
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        from friday.core.config import find_project_root

        root = find_project_root()
        protected.append(root / "src" / "friday")
        protected.append(root / "src" / "friday_deep")
    except Exception:  # pragma: no cover - defensive
        pass
    # De-duplicate while preserving order.
    seen: list[Path] = []
    for item in protected:
        resolved = item.resolve()
        if resolved not in seen:
            seen.append(resolved)
    return tuple(seen)


_SHARED: WorkspacePolicy | None = None


def shared_policy(settings=None) -> WorkspacePolicy:
    """Return the process-wide policy, building it once."""
    global _SHARED
    if _SHARED is None:
        _SHARED = WorkspacePolicy.from_settings(settings)
    return _SHARED


def reset_shared_policy() -> None:
    """Drop the cached policy (used by tests and by config reload)."""
    global _SHARED
    _SHARED = None
