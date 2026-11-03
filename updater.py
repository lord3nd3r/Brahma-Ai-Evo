"""Check for and apply fast-forward updates from the Brahma GitHub repository."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.update_policy import git_remote_url, linux_disabled_message, self_update_enabled

# Kept for callers that imported the historical Windows upstream URL.
REMOTE = "https://github.com/titechprabhasolutions/Brahma---personal.git"
BRANCH = "main"


def _run_git(base_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=base_dir,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def update_from_github(base_dir: Path) -> bool:
    """Update a clean Git checkout and return whether the app should restart."""
    if not self_update_enabled():
        if sys.platform.startswith("linux"):
            print(linux_disabled_message())
        return False

    if not (base_dir / ".git").exists():
        return False

    status = _run_git(base_dir, "status", "--porcelain")
    if status.returncode != 0 or status.stdout.strip():
        return False

    remote = _run_git(base_dir, "remote", "get-url", "origin")
    if remote.returncode != 0 or not remote.stdout.strip():
        url = git_remote_url()
        if not url:
            print("[Updater] No git origin and no BRAHMA_UPDATE_REMOTE; not adding an upstream.")
            return False
        _run_git(base_dir, "remote", "add", "origin", url)

    fetch = _run_git(base_dir, "fetch", "origin", BRANCH, "--quiet")
    if fetch.returncode != 0:
        return False

    local = _run_git(base_dir, "rev-parse", "HEAD")
    upstream = _run_git(base_dir, "rev-parse", f"origin/{BRANCH}")
    if local.returncode != 0 or upstream.returncode != 0:
        return False
    if local.stdout.strip() == upstream.stdout.strip():
        return False

    ancestor = _run_git(base_dir, "merge-base", "--is-ancestor", "HEAD", f"origin/{BRANCH}")
    if ancestor.returncode != 0:
        return False

    pull = _run_git(base_dir, "pull", "--ff-only", "origin", BRANCH)
    if pull.returncode != 0:
        return False
    return True


def restart_application(base_dir: Path) -> None:
    """Replace the current process with the updated application."""
    os.execv(sys.executable, [sys.executable, str(base_dir / "main.py"), *sys.argv[1:]])
