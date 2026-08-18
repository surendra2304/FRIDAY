import subprocess
import re
import sys

def git_ls_env():
    """Return list of tracked .env files (should be empty)."""
    result = subprocess.run(["git", "ls-files", ".env"], capture_output=True, text=True)
    return result.stdout.strip().splitlines()

def scan_for_keys():
    """Search all tracked files for potential API key patterns.
    Looks for long alphanumeric strings (35+ chars) that could be keys.
    Returns a list of (filename, line) tuples where a match was found.
    """
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    files = result.stdout.strip().splitlines()
    suspicious = []
    pattern = re.compile(r"[A-Za-z0-9_]{35,}")
    for f in files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh, start=1):
                    if pattern.search(line):
                        suspicious.append((f, i))
        except Exception:
            continue
    return suspicious

def main():
    env_files = git_ls_env()
    if env_files:
        print("ERROR: Tracked .env files found:")
        for f in env_files:
            print(f"  {f}")
        sys.exit(1)
    matches = scan_for_keys()
    if matches:
        print("ERROR: Potential secret patterns found in tracked files:")
        for f, line_no in matches:
            print(f"  {f}: line {line_no}")
        sys.exit(1)
    print("Security check passed: no .env tracked and no obvious key patterns.")
    with open("security_report.txt", "w", encoding="utf-8") as out:
        out.write("Security check passed. No .env tracked and no secret patterns detected.\n")

if __name__ == "__main__":
    main()
