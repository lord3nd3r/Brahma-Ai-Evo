"""Whether Brahma may update itself from GitHub.

Windows keeps the historical upstream, ``titechprabhasolutions/Brahma---personal``.
This checkout is a fork, so Linux does not contact that repository unless the
user opts in:

* ``BRAHMA_SKIP_UPDATE=1`` — off on every platform
* ``BRAHMA_ENABLE_UPDATE=1`` — on Linux, allow a fast-forward of the current origin
* ``BRAHMA_UPDATE_REMOTE`` — explicit git URL to add when origin is missing
* ``BRAHMA_UPDATE_REPO`` — explicit ``owner/name`` for GitHub commit/release checks
"""

from __future__ import annotations

import os
import sys

# Historical upstream. Windows-only unless BRAHMA_UPDATE_REPO / BRAHMA_UPDATE_REMOTE is set.
UPSTREAM_SLUG = "titechprabhasolutions/Brahma---personal"
UPSTREAM_GIT_URL = "https://github.com/titechprabhasolutions/Brahma---personal.git"

_LINUX_OFF_MESSAGE = (
    "[Updater] Git self-update is off on Linux. This fork will not pull "
    "titechprabhasolutions/Brahma---personal. Set BRAHMA_ENABLE_UPDATE=1 to "
    "fast-forward the current origin, BRAHMA_UPDATE_REMOTE to an explicit git URL, "
    "or BRAHMA_UPDATE_REPO=owner/name for GitHub commit checks."
)


def skip_requested() -> bool:
    return os.environ.get("BRAHMA_SKIP_UPDATE", "").strip() == "1"


def self_update_enabled() -> bool:
    if skip_requested():
        return False
    if sys.platform.startswith("linux"):
        return os.environ.get("BRAHMA_ENABLE_UPDATE", "").strip() == "1"
    return True


def linux_disabled_message() -> str:
    return _LINUX_OFF_MESSAGE


def github_repo_slug() -> str | None:
    """``owner/name`` for GitHub API checks, or None when checks must not run."""
    explicit = os.environ.get("BRAHMA_UPDATE_REPO", "").strip().strip("/")
    if explicit:
        return explicit
    if sys.platform.startswith("linux"):
        return None
    return UPSTREAM_SLUG


def git_remote_url() -> str | None:
    """URL to add as origin when the checkout has none. None means do not invent one."""
    explicit = os.environ.get("BRAHMA_UPDATE_REMOTE", "").strip()
    if explicit:
        return explicit
    if sys.platform.startswith("linux"):
        return None
    return UPSTREAM_GIT_URL
