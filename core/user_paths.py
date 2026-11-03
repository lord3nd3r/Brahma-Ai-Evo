"""Per-user Brahma directories.

Windows keeps the historical layout: everything lives under
``%LOCALAPPDATA%\\BrahmaAI`` and the startup log stays in
``%LOCALAPPDATA%\\Brahma Evo\\startup.log``.

Linux uses the XDG base directory spec through this module:

* config  -> ``$XDG_CONFIG_HOME/BrahmaAI`` (default ``~/.config/BrahmaAI``)
* data    -> ``$XDG_DATA_HOME/BrahmaAI`` (default ``~/.local/share/BrahmaAI``)
* state   -> ``$XDG_STATE_HOME/BrahmaAI`` (default ``~/.local/state/BrahmaAI``)
* cache   -> ``$XDG_CACHE_HOME/BrahmaAI`` (default ``~/.cache/BrahmaAI``)

Existing call sites write ``get_user_data_dir() / "config"``. On Linux that
division is redirected to the XDG config directory so every caller shares one
helper without a Windows path change.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _xdg(env_name: str, default: Path) -> Path:
    raw = os.environ.get(env_name, "").strip()
    return Path(raw).expanduser() if raw else default


def get_user_config_dir() -> Path:
    """Settings, API keys, and other configuration."""
    if _is_linux():
        base = _xdg("XDG_CONFIG_HOME", Path.home() / ".config")
        return _mkdir(base / "BrahmaAI")
    return _mkdir(get_user_data_dir() / "config")


def get_user_cache_dir() -> Path:
    if _is_linux():
        base = _xdg("XDG_CACHE_HOME", Path.home() / ".cache")
        return _mkdir(base / "BrahmaAI")
    return _mkdir(get_user_data_dir() / "cache")


def get_user_state_dir() -> Path:
    """Logs and other state that is not configuration."""
    if _is_linux():
        base = _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state")
        return _mkdir(base / "BrahmaAI")
    return _mkdir(get_user_data_dir())


def deliverables_dir() -> Path:
    """Generated images, charts, and other user-visible files."""
    return _mkdir(get_user_data_dir() / "deliverables")


def startup_log_path(fallback: Path | None = None) -> Path:
    """Path of the startup log.

    Windows: ``%LOCALAPPDATA%\\Brahma Evo\\startup.log`` (unchanged).
    Linux: ``$XDG_STATE_HOME/BrahmaAI/startup.log``.
    """
    if _is_linux():
        return get_user_state_dir() / "startup.log"
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        root = str(fallback) if fallback is not None else os.path.expanduser("~")
    return Path(root) / "Brahma Evo" / "startup.log"


class _LinuxDataPath(Path):
    """Data directory whose ``/ "config"`` joins the XDG config dir."""

    def __truediv__(self, key):
        if str(key) == "config":
            return get_user_config_dir()
        return super().__truediv__(key)


def get_user_data_dir() -> Path:
    """Mutable user data (memory, skills, deliverables, network maps)."""
    if _is_windows():
        app_data = os.getenv("LOCALAPPDATA", os.path.expanduser("~"))
        return _mkdir(Path(app_data) / "BrahmaAI")
    if _is_linux():
        base = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")
        path = _mkdir(base / "BrahmaAI")
        return _LinuxDataPath(path)
    app_data = os.getenv("LOCALAPPDATA", os.path.expanduser("~"))
    return _mkdir(Path(app_data) / "BrahmaAI")
