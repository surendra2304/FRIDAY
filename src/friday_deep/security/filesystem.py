from pathlib import Path


class FileAccessDenied(PermissionError):
    pass


class SecureWorkspace:
    BLOCKED_NAMES = {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "id_rsa",
        "id_ed25519",
    }
    BLOCKED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".db", ".sqlite", ".sqlite3", ".kdbx"}
    BLOCKED_DIRS = {".git", ".ssh", ".gnupg", ".aws", ".azure", ".config"}

    def __init__(self, root):
        self.root = Path(root).resolve()

    def resolve(self, user_path: str) -> Path:
        p = Path(user_path)
        if p.is_absolute() or p.anchor:
            raise FileAccessDenied("Absolute paths are denied.")
        target = (self.root / p).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as e:
            raise FileAccessDenied("Path traversal outside workspace is denied.") from e
        self.check(target)
        return target

    def check(self, target: Path):
        name = target.name.lower()
        if name in self.BLOCKED_NAMES:
            raise FileAccessDenied("Sensitive file access denied.")
        if any(name.endswith(s) for s in self.BLOCKED_SUFFIXES):
            raise FileAccessDenied("Sensitive file type denied.")
        parts = [x.lower() for x in target.relative_to(self.root).parts]
        if any(x in self.BLOCKED_DIRS for x in parts):
            raise FileAccessDenied("Sensitive directory access denied.")

    def read_text(self, user_path, max_bytes=131072) -> str:
        p = self.resolve(user_path)
        if not p.is_file():
            raise FileAccessDenied("Not a regular file.")
        if p.stat().st_size > max_bytes:
            raise FileAccessDenied("File exceeds configured read limit.")
        raw = p.read_bytes()
        if b"\x00" in raw[:4096]:
            raise FileAccessDenied("Binary files are denied.")
        return raw.decode("utf-8", "replace")
