import os
import subprocess
import sys
import time
from pathlib import Path

from performance_monitor import monitor_performance
from security_check import run_security_check
from git_helper import git_commit_and_push

def run_pytest():
    """Run pytest suite, separating mock and live tests."""
    # Ensure we have pytest installed
    try:
        import pytest  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pytest"])
    # Run pytest with -q for quiet output
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "d:/FRIDAY/tests"], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print("Pytest failures detected.")
        sys.exit(1)
    return result.stdout

def run_real_gemini_tests():
    """Execute live tests marked with @pytest.mark.live."""
    # Run only live tests
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-m", "live", "d:/FRIDAY/tests"], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print("Live Gemini tests failed.")
        sys.exit(1)
    return result.stdout

def main():
    # Step 1: Security scan
    print("Running security scan...")
    run_security_check()

    # Step 2: Full pytest suite (mock + live)
    print("Running full pytest suite...")
    with monitor_performance(name="full_pytest_suite"):
        run_pytest()

    # Step 3: Real Gemini mini-tests
    print("Running real Gemini integration tests...")
    with monitor_performance(name="live_gemini_tests"):
        run_real_gemini_tests()

    # Step 4: Documentation updates (handled by separate scripts / manual steps)
    # Placeholder for documentation update logic.

    # Step 5: Git commit & push
    print("Committing changes...")
    git_commit_and_push(message="test(integration): verify FRIDAY end-to-end with real Gemini")

if __name__ == "__main__":
    main()
