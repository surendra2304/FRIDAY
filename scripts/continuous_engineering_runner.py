#!/usr/bin/env python3
"""Persistent multi-repository engineering runner for scheduled FRIDAY Universe workstreams."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import textwrap
from datetime import datetime, timezone
from pathlib import Path

OWNER = "surendra2304"
WORKSTREAMS = {
    1: ("FRIDAY", "Inference", "Memora"),
    2: ("Stratex", "IntelX", "Futuris"),
    3: ("VyralX", "Forge", "Sentinel", "Cortex"),
}
MIN_WORK_SECONDS = 31 * 60
BRANCH_PREFIX = "automation/friday-universe-task"
STATE_PREFIX = "automation/friday-universe-task-state"

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def control_root():
    return Path(__file__).resolve().parents[1]

def run_dir(task):
    base = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
    return base / f"friday-ce-{os.environ.get('GITHUB_RUN_ID','local')}-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}-task-{task}"

def command(args, cwd=None, env=None, timeout=900, check=True):
    p = subprocess.run(args, cwd=str(cwd) if cwd else None, env=env, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    if check and p.returncode:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(args)}\n{p.stdout[-10000:]}")
    return p

def git(path, *args, env=None, check=True, timeout=900):
    return command(["git", *args], cwd=path, env=env, check=check, timeout=timeout)

def clone(name, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    command(["git", "clone", "--branch", "main",
             f"https://github.com/{OWNER}/{name}.git", str(destination)], timeout=600)
    return destination

def prepare_branch(path, task, state=False):
    branch = f"{STATE_PREFIX}-{task}" if state else f"{BRANCH_PREFIX}-{task}"
    git(path, "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main")
    remote = git(path, "ls-remote", "--heads", "origin", branch, check=False)
    if remote.returncode == 0 and remote.stdout.strip():
        git(path, "fetch", "origin", f"{branch}:refs/remotes/origin/{branch}")
        git(path, "checkout", "-B", branch, f"origin/{branch}")
        if not state:
            # Bring an existing work branch forward without discarding prior engineering.
            merged = git(path, "merge", "--no-edit", "origin/main", check=False)
            if merged.returncode:
                (path / ".friday-merge-conflict.md").write_text(
                    "Resolve the merge conflict with current main while preserving valid prior work.\n",
                    encoding="utf-8")
    elif state:
        # The state branch is intentionally an orphan with only task handoff files.
        git(path, "checkout", "--orphan", branch)
        git(path, "rm", "-rf", ".", check=False)
    else:
        git(path, "checkout", "-B", branch, "origin/main")
    git(path, "config", "user.name", "FRIDAY Universe Engineering")
    git(path, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    if not state:
        exclude = path / ".git" / "info" / "exclude"
        with exclude.open("a", encoding="utf-8") as f:
            f.write("\n.venv/\nnode_modules/\n__pycache__/\n.pytest_cache/\n")
    return branch

def state_files(state, task):
    d = state / "handoffs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"task-{task}-checkpoint.md", d / f"task-{task}-next-run.md"

def task_instructions(task):
    p = control_root() / "ops" / "continuous-engineering" / "tasks" / f"task-{task}.md"
    if not p.exists():
        raise RuntimeError(f"Missing task instructions: {p}")
    return p.read_text(encoding="utf-8")

def bootstrap_deps(path, name):
    notes = []
    try:
        req, pyproject = path / "requirements.txt", path / "pyproject.toml"
        if req.exists() or pyproject.exists():
            venv = path / ".venv"
            if not venv.exists():
                command([sys.executable, "-m", "venv", str(venv)], timeout=120)
            pip = venv / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
            if req.exists():
                command([str(pip), "install", "-r", str(req)], cwd=path, timeout=600)
                if pyproject.exists():
                    command([str(pip), "install", "-e", ".[dev]"], cwd=path, timeout=600)
            else:
                command([str(pip), "install", "-e", ".[dev]"], cwd=path, timeout=600)
            notes.append(f"{name}: Python runtime and dev/test dependencies installed in .venv")
        if (path / "package.json").exists():
            if (path / "package-lock.json").exists():
                command(["npm", "ci", "--no-audit", "--no-fund"], cwd=path, timeout=900)
            elif (path / "pnpm-lock.yaml").exists():
                command(["corepack", "pnpm", "install", "--frozen-lockfile"], cwd=path, timeout=900)
            elif (path / "yarn.lock").exists():
                command(["corepack", "yarn", "install", "--immutable"], cwd=path, timeout=900)
            notes.append(f"{name}: Node dependencies bootstrapped")
    except Exception as exc:
        notes.append(f"{name}: dependency bootstrap failed (agent should diagnose): {exc}")
    return notes

def do_prepare(task):
    root = run_dir(task)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    state, _ = prepare_state_checkout(task, root)
    checkpoint, next_run = state_files(state, task)
    instructions = task_instructions(task)
    if not checkpoint.exists():
        checkpoint.write_text(
            f"# Task {task} checkpoint\n\nCreated: {now()}\n\n"
            "Fresh workstream. Inspect current code and existing issues first, then implement a concrete, "
            "high-impact feature or fix and verify it.\n\n## Workstream\n\n" + instructions + "\n",
            encoding="utf-8")
    if not next_run.exists():
        next_run.write_text(
            f"# Task {task}: next-run instructions\n\n"
            "Read this file and the checkpoint before coding. Resume incomplete implementation instead of "
            "starting over. Make real code and test changes, run tests/builds, fix failures, and rewrite "
            "both this file and the checkpoint with exact results and actionable next coding steps before exit.\n",
            encoding="utf-8")
    meta = {
        "task": task,
        "checkpoint_hash": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "next_run_hash": hashlib.sha256(next_run.read_bytes()).hexdigest(),
        "prepared_at": now(),
    }
    (root / "initial-state.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    repos = root / "repos"
    repos.mkdir()
    for name in WORKSTREAMS[task]:
        p = clone(name, repos / name)
        prepare_branch(p, task)
    notes = []
    for name in WORKSTREAMS[task]:
        notes.extend(bootstrap_deps(repos / name, name))
    (root / "dependency-bootstrap.md").write_text(
        "# Dependency bootstrap\n\n" + "\n".join("- " + item for item in notes) + "\n", encoding="utf-8")
    print(json.dumps({"task": task, "workspaces": [str(repos / n) for n in WORKSTREAMS[task]],
                      "state_dir": str(state), "dependency_notes": notes}, indent=2))

def build_prompt(task, state, repos, pass_no, elapsed):
    checkpoint, next_run = state_files(state, task)
    parts = [
        "# FRIDAY Universe continuous engineering",
        f"Task {task}; pass {pass_no}; active working time {elapsed}s; UTC {now()}",
        task_instructions(task),
        "## Previous checkpoint: read and continue",
        checkpoint.read_text(encoding="utf-8"),
        "## Next-run instructions from the previous cycle",
        next_run.read_text(encoding="utf-8"),
        "## Assigned repository directories",
    ]
    for name in WORKSTREAMS[task]:
        parts.append(f"- {name}: {repos / name}")
    parts.extend([
        "## Required execution behavior",
        "This is a coding session, not a reporting session. Inspect code and Git status, select a concrete "
        "unfixed issue or feature, edit implementation and tests, run relevant checks, and fix failures.",
        "Work across each assigned repository where a justified change exists; do not force empty or cosmetic edits.",
        "Where a repository has a .venv directory, use that repository-specific environment to run Python tests and linters (for example .venv/bin/python -m pytest) so dependencies do not bleed across projects.",
        "Long-term target is thousands of lines of meaningful code across useful features, integrations, tests and fixes; never pad code just to hit a line count.",
        "Do not commit or push. The workflow publisher handles commits and PRs after the session.",
        "Do not merge PRs, force-push, reset user work, change production/cloud infrastructure, or work outside assigned repositories and the two state files.",
        "Never read, print, or transmit secrets. Do not edit any file in the state checkout except its task checkpoint and next-run instructions.",
        "Before ending this pass, rewrite the checkpoint with real files changed, tests/commands and results, incomplete work and blockers. Rewrite the next-run instructions as a concrete continuation prompt with exact paths, first coding action and tests to execute. Do not leave generic placeholders.",
        "After handoff updates, summarize actual code changes and test outcomes. The runner will start another coding pass if needed to reach the minimum active work duration.",
    ])
    return "\n\n".join(parts)

def do_run(task):
    root = run_dir(task)
    repos, state = root / "repos", root / "state"
    if not repos.exists() or not state.exists():
        raise RuntimeError("Prepared workspaces are missing; prepare must finish before coding.")
    agent = os.environ.get("CODE_AGENT", "codex").strip().lower()
    if agent not in {"codex", "copilot"}:
        raise RuntimeError(f"Unsupported CODE_AGENT={agent!r}; use codex or copilot.")
    if agent == "codex" and not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError("Codex selected but OPENAI_API_KEY is missing.")
    if agent == "copilot" and not os.environ.get("COPILOT_GITHUB_TOKEN", "").strip():
        raise RuntimeError("Copilot selected but COPILOT_GITHUB_TOKEN is missing.")
    checkpoint, next_run = state_files(state, task)
    before = json.loads((root / "initial-state.json").read_text(encoding="utf-8"))
    codex_home = root / "codex-home"
    codex_home.mkdir(exist_ok=True)
    # Codex uses its default environment policy to exclude key/token/secret vars from tool shells.
    if agent == "codex" and os.environ.get("CODEX_PROVIDER", "openai") == "openrouter":
        codex_config = (
            'model = "openai/gpt-5.6-sol"\n'
            'model_provider = "openrouter"\n'
            'model_reasoning_effort = "high"\n\n'
            '[model_providers.openrouter]\n'
            'name = "OpenRouter"\n'
            'base_url = "https://openrouter.ai/api/v1"\n'
            'wire_api = "responses"\n\n'
            '[model_providers.openrouter.auth]\n'
            'command = "sh"\n'
            'args = ["-c", "echo $OPENROUTER_API_KEY"]\n\n'
            '[shell_environment_policy]\n'
            'ignore_default_excludes = false\n'
        )
        (codex_home / "config.toml").write_text(codex_config, encoding="utf-8")
    elif agent == "codex":
        (codex_home / "config.toml").write_text(
            '[shell_environment_policy]\nignore_default_excludes = false\n', encoding="utf-8"
        )
    start = time.monotonic()
    pass_no = 0
    while time.monotonic() - start < MIN_WORK_SECONDS:
        pass_no += 1
        elapsed = int(time.monotonic() - start)
        prompt_path = root / f"pass-{pass_no}-prompt.md"
        prompt_path.write_text(build_prompt(task, state, repos, pass_no, elapsed), encoding="utf-8")
        log_path, last_message = root / f"pass-{pass_no}.jsonl", root / f"pass-{pass_no}-final.md"
        prompt_text = prompt_path.read_text(encoding="utf-8")
        if agent == "codex":
            cmd = ["codex", "exec", "--sandbox", "workspace-write", "--cd", str(repos / WORKSTREAMS[task][0])]
            for name in WORKSTREAMS[task][1:]:
                cmd.extend(["--add-dir", str(repos / name)])
            cmd.extend(["--add-dir", str(state), "--json", "--output-last-message", str(last_message), "-"])
            work_cwd = repos / WORKSTREAMS[task][0]
        else:
            cmd = [
                "copilot", "-p", prompt_text, "--model", os.environ.get("COPILOT_MODEL", "gpt-6-astra"),
                "--allow-all-tools", "--allow-all-paths", "--no-ask-user",
                "--secret-env-vars", "COPILOT_GITHUB_TOKEN", "-s",
            ]
            work_cwd = root
        env = os.environ.copy()
        if agent == "codex":
            env["CODEX_HOME"] = str(codex_home)
            env.pop("COPILOT_GITHUB_TOKEN", None)
        for key in ("GH_TOKEN", "GITHUB_TOKEN", "CONTINUOUS_ENGINEERING_TOKEN", "FRIDAY_AUTOMATION_TOKEN"):
            env.pop(key, None)
        print(f"Starting task {task} coding pass {pass_no} with {agent}; active time {elapsed}s")
        try:
            with log_path.open("w", encoding="utf-8") as log:
                if agent == "codex":
                    result = subprocess.run(cmd, input=prompt_text, text=True,
                                            cwd=str(work_cwd), env=env,
                                            stdout=log, stderr=subprocess.STDOUT, timeout=24*60, check=False)
                else:
                    result = subprocess.run(cmd, text=True, cwd=str(work_cwd), env=env,
                                            stdout=log, stderr=subprocess.STDOUT, timeout=24*60, check=False)
                    if result.returncode == 0:
                        last_message.write_text(log_path.read_text(encoding="utf-8", errors="replace")[-12000:],
                                                encoding="utf-8")
        except subprocess.TimeoutExpired:
            # A timed-out model pass is still a failed run that needs a durable next-run handoff.
            with log_path.open("a", encoding="utf-8") as log:
                log.write("\nRunner: Codex exceeded the 24-minute per-pass timeout and was terminated.\n")
            result = subprocess.CompletedProcess(cmd, 124, "Codex pass timed out after 24 minutes")
        if result.returncode:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-12000:]
            changes = {n: git(repos / n, "status", "--short").stdout.strip().splitlines() for n in WORKSTREAMS[task]}
            failure_at = now()
            with checkpoint.open("a", encoding="utf-8") as f:
                f.write(f"\n\n## Interrupted coding pass ({failure_at})\n\n"
                        f"Codex pass {pass_no} failed with exit code {result.returncode}. "
                        f"Inspect log {log_path.name} before deciding whether partial changes are usable.\n\n"
                        f"Log tail:\n\n{textwrap.indent(tail[-5000:], '    ')}\n")
            lines = [f"# Task {task}: next-run instructions",
                     f"\nUpdated after failed Codex pass at {failure_at}. Do not assume partial edits are correct.",
                     f"\nFirst inspect the log {log_path.name}, the checkpoint, and all listed repository diffs. "
                     "Fix the underlying runner/model error or discard only clearly broken partial edits, then resume implementation and tests."]
            for name, files in changes.items():
                lines.append(f"\n## {name}")
                lines.extend("- " + item for item in files[:80] or ["No working-tree diff detected."])
            next_run.write_text("\n".join(lines) + "\n", encoding="utf-8")
            failure_summary = {
                "task": task, "active_seconds": int(time.monotonic() - start),
                "passes": pass_no, "repo_changes": changes, "checkpoint_updated": True,
                "next_run_updated": True, "finished_at": now(), "publish_code": False,
                "failure": f"Codex pass {pass_no} exited {result.returncode}",
            }
            (root / "run-summary.json").write_text(json.dumps(failure_summary, indent=2), encoding="utf-8")
            raise RuntimeError(f"Codex pass {pass_no} failed; handoff saved for the next run:\n{tail}")
        if not checkpoint.exists() or not next_run.exists():
            raise RuntimeError("The coding agent removed a required state file.")
    elapsed = int(time.monotonic() - start)
    changed = {n: git(repos / n, "status", "--short").stdout.strip().splitlines() for n in WORKSTREAMS[task]}
    # Deterministic fallback guarantees the next cycle has a new, useful continuation prompt.
    chash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    nhash = hashlib.sha256(next_run.read_bytes()).hexdigest()
    if chash == before["checkpoint_hash"]:
        with checkpoint.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## Runner checkpoint enforcement ({now()})\n\n"
                    "Coding agent did not rewrite the checkpoint; next run must inspect the active work branches and test results before extending implementation.\n")
    if nhash == before["next_run_hash"]:
        lines = [f"# Task {task}: next-run instructions",
                 f"\nUpdated by runner at {now()} because the coding pass did not revise the prompt.",
                 "\nRead the checkpoint first, then inspect these active work branches and continue implementation."]
        for name, changes in changed.items():
            lines.append(f"\n## {name}")
            lines.extend("- " + line for line in changes[:60] or ["No code diff detected. Inspect repository TODOs and failing tests, then implement a concrete fix."])
        lines.append("\nFirst action: inspect diffs and tests, fix failures, then implement the highest-impact unfinished feature. Rewrite this file with exact next steps before exit.")
        next_run.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "task": task, "active_seconds": elapsed, "passes": pass_no, "repo_changes": changed,
        "checkpoint_updated": hashlib.sha256(checkpoint.read_bytes()).hexdigest() != before["checkpoint_hash"],
        "next_run_updated": hashlib.sha256(next_run.read_bytes()).hexdigest() != before["next_run_hash"],
        "finished_at": now(),
    }
    (root / "run-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if elapsed < MIN_WORK_SECONDS:
        raise RuntimeError(f"Active coding duration {elapsed}s did not meet {MIN_WORK_SECONDS}s minimum.")

def get_push_auth():
    token = os.environ.get("CONTINUOUS_ENGINEERING_TOKEN", "").strip()
    if not token:
        raise RuntimeError("CONTINUOUS_ENGINEERING_TOKEN is missing; it must allow Contents write and Pull requests write on all ten repositories.")
    return base64.b64encode(f"x-access-token:{token}".encode()).decode()

def push(repo_path, branch, auth):
    env = os.environ.copy()
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
    env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {auth}"
    command(["git", "push", "--set-upstream", "origin", branch], cwd=repo_path, env=env, timeout=600)

def do_publish(task):
    root = run_dir(task)
    repos, state = root / "repos", root / "state"
    if not state.exists():
        raise RuntimeError("No prepared task state exists; preserve the workflow artifact and diagnose preparation.")
    auth = get_push_auth()
    gh_env = os.environ.copy()
    gh_env["GH_TOKEN"] = os.environ["CONTINUOUS_ENGINEERING_TOKEN"]
    summary_path = root / "run-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {
        "task": task, "active_seconds": 0, "passes": 0, "repo_changes": {},
        "checkpoint_updated": False, "next_run_updated": False, "publish_code": False,
        "failure": "Coding step did not produce a run summary; only persist the handoff.",
    }
    publish_code = bool(summary.get("publish_code", False))
    branch = f"{BRANCH_PREFIX}-{task}"
    urls = []
    for name in (WORKSTREAMS[task] if publish_code else ()):
        path = repos / name
        diff_check = git(path, "diff", "--check", check=False)
        if diff_check.returncode:
            raise RuntimeError(f"{name}: git diff --check failed:\n{diff_check.stdout}")
        if not git(path, "status", "--porcelain").stdout.strip():
            print(f"{name}: no code changes to publish.")
            continue
        git(path, "add", "-A")
        git(path, "commit", "-m", f"feat: continue FRIDAY Universe task {task} engineering")
        push(path, branch, auth)
        full_name = f"{OWNER}/{name}"
        view = command(["gh", "pr", "view", branch, "--repo", full_name, "--json", "url,state"],
                       env=gh_env, check=False, timeout=180)
        existing = {}
        if view.returncode == 0:
            try:
                existing = json.loads(view.stdout)
            except json.JSONDecodeError:
                existing = {}
        if existing.get("state") == "OPEN":
            urls.append(existing["url"])
        else:
            body = (
                f"## Continuous engineering task {task}\n\n"
                f"Workstream repositories: {', '.join(WORKSTREAMS[task])}.\n\n"
                "Contains implementation and tests produced by the scheduled coding worker. "
                "Please inspect the diff and CI checks before merging.\n\n"
                f"Workflow run: {os.environ.get('GITHUB_SERVER_URL','https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY','')}/actions/runs/{os.environ.get('GITHUB_RUN_ID','')}\n")
            created = command(["gh", "pr", "create", "--repo", full_name, "--base", "main", "--head", branch,
                               "--title", f"feat: continue FRIDAY Universe task {task} engineering",
                               "--body", body], env=gh_env, timeout=180)
            urls.append(created.stdout.strip().splitlines()[-1])
    checkpoint, next_run = state_files(state, task)
    if not checkpoint.exists() or not next_run.exists():
        raise RuntimeError("Checkpoint or next-run instructions are missing; refusing to publish an incomplete handoff.")
    git(state, "add", str(checkpoint.relative_to(state)), str(next_run.relative_to(state)))
    if git(state, "status", "--porcelain").stdout.strip():
        git(state, "commit", "-m", f"chore: persist task {task} continuation handoff")
        push(state, f"{STATE_PREFIX}-{task}", auth)
    summary["pull_requests"] = urls
    summary["published_at"] = now()
    print(json.dumps(summary, indent=2))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"## Task {task} coding run\n\n- Active coding time: {summary['active_seconds']} seconds\n")
            f.write(f"- Coding passes: {summary['passes']}\n- Checkpoint revised: {summary['checkpoint_updated']}\n")
            f.write(f"- Next-run instructions revised: {summary['next_run_updated']}\n")
            if urls:
                f.write("- Pull requests:\n" + "".join(f"  - {url}\n" for url in urls))
            else:
                f.write("- No code changes were available for PR publication.\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "run", "publish"))
    parser.add_argument("--task", type=int, choices=(1, 2, 3), required=True)
    args = parser.parse_args()
    try:
        {"prepare": do_prepare, "run": do_run, "publish": do_publish}[args.mode](args.task)
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    return 0

def prepare_state_checkout(task, root):
    state = root / "state"
    if state.exists():
        shutil.rmtree(state)
    state.parent.mkdir(parents=True, exist_ok=True)
    command(["git", "clone", "--depth", "1", "--branch", "main",
             f"https://github.com/{OWNER}/FRIDAY.git", str(state)], timeout=600)
    branch = f"{STATE_PREFIX}-{task}"
    probe = git(state, "ls-remote", "--heads", "origin", branch, check=False)
    if probe.returncode == 0 and probe.stdout.strip():
        git(state, "fetch", "--depth=1", "origin", f"{branch}:refs/remotes/origin/{branch}")
        git(state, "checkout", "-B", branch, f"origin/{branch}")
    else:
        git(state, "checkout", "--orphan", branch)
        git(state, "rm", "-rf", ".", check=False)
        # An orphan checkout may leave the old main files as untracked.
        git(state, "clean", "-fdx")
    git(state, "config", "user.name", "FRIDAY Universe Engineering")
    git(state, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    return state, branch

if __name__ == "__main__":
    raise SystemExit(main())
