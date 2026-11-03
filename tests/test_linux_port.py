"""Linux port checks that do not need a microphone, GPU, or speakers."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest


def test_installer_and_ci_are_linux_safe():
    script = Path("installer/install.sh").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/build-all-platforms.yml").read_text(encoding="utf-8")
    assert "brahma-evo.png" in script
    assert "brahma-evo.ico" not in script
    assert "libgl1-mesa-glx" not in workflow
    assert "libgl1" in workflow


def test_requirements_mark_windows_packages():
    text = Path("requirements.txt").read_text(encoding="utf-8")
    assert "pyaudio" not in text.lower()
    for package in ("comtypes", "pycaw", "win10toast", "pywinauto", "pygetwindow"):
        assert f"{package}; sys_platform == \"win32\"" in text


def test_linux_xdg_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from core.user_paths import (
        deliverables_dir,
        get_user_cache_dir,
        get_user_config_dir,
        get_user_data_dir,
        get_user_state_dir,
        startup_log_path,
    )

    data = get_user_data_dir()
    config = get_user_config_dir()
    assert data == tmp_path / "share" / "BrahmaAI"
    assert config == tmp_path / "config" / "BrahmaAI"
    assert data / "config" == config
    assert get_user_state_dir() == tmp_path / "state" / "BrahmaAI"
    assert get_user_cache_dir() == tmp_path / "cache" / "BrahmaAI"
    assert deliverables_dir() == data / "deliverables"
    assert startup_log_path(tmp_path) == tmp_path / "state" / "BrahmaAI" / "startup.log"


def test_windows_paths_stay_under_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    local = tmp_path / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    from core.user_paths import get_user_config_dir, get_user_data_dir, startup_log_path

    data = get_user_data_dir()
    assert data == local / "BrahmaAI"
    assert get_user_config_dir() == local / "BrahmaAI" / "config"
    assert startup_log_path(tmp_path) == local / "Brahma Evo" / "startup.log"


def test_game_updater_imports_without_winreg():
    import actions.game_updater as game_updater

    assert callable(game_updater.game_updater)
    assert game_updater._find_steam_path() is None or Path(game_updater._find_steam_path()).exists()


def test_linux_update_is_off_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("BRAHMA_ENABLE_UPDATE", raising=False)
    monkeypatch.delenv("BRAHMA_SKIP_UPDATE", raising=False)
    from core.update_policy import github_repo_slug, self_update_enabled
    from updater import update_from_github

    assert self_update_enabled() is False
    assert github_repo_slug() is None
    assert update_from_github(tmp_path) is False


def test_linux_update_can_be_enabled(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("BRAHMA_ENABLE_UPDATE", "1")
    monkeypatch.setenv("BRAHMA_UPDATE_REPO", "lord3nd3r/Brahma-Ai-Evo")
    from core.update_policy import github_repo_slug, self_update_enabled

    assert self_update_enabled() is True
    assert github_repo_slug() == "lord3nd3r/Brahma-Ai-Evo"


def test_windows_update_policy_unchanged(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("BRAHMA_SKIP_UPDATE", raising=False)
    from core.update_policy import UPSTREAM_SLUG, github_repo_slug, self_update_enabled

    assert self_update_enabled() is True
    assert github_repo_slug() == UPSTREAM_SLUG


def test_pulse_devices_outrank_alsa_hw_and_windows_apis():
    from core.audio_devices import linux_device_score

    pulse = linux_device_score("Built-in Audio Analog Stereo", "PulseAudio")
    pipewire = linux_device_score("pipewire", "ALSA")
    default = linux_device_score("default", "ALSA")
    hw = linux_device_score("hw:0,0", "ALSA")
    mme = linux_device_score("Microphone (Realtek HD Audio)", "MME")
    assert pulse > pipewire > default > hw
    assert pulse > mme
    assert hw > mme or pulse > mme


def test_autostart_desktop_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from core.platform_support import autostart_desktop_path, autostart_enabled, set_autostart

    assert autostart_enabled() is False
    assert set_autostart(True, "/usr/bin/python3 /opt/brahma/main.py --startup", "/opt/brahma/icon.png")
    path = autostart_desktop_path()
    text = path.read_text(encoding="utf-8")
    assert "Type=Application" in text
    assert "Exec=/usr/bin/python3 /opt/brahma/main.py --startup" in text
    assert "Icon=/opt/brahma/icon.png" in text
    assert "X-GNOME-Autostart-enabled=true" in text
    assert autostart_enabled() is True
    assert set_autostart(False, "unused")
    assert not path.exists()


def test_linux_reminder_uses_systemd_not_schtasks(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    calls = []

    def _fake_timer(unit, when, command, description, on_calendar=None):
        calls.append((unit, command, description))
        return True, "Timer set."

    monkeypatch.setattr("core.platform_support.install_user_timer", _fake_timer)
    from actions.reminder import reminder

    when = datetime.now() + timedelta(days=1)
    message = reminder({
        "date": when.strftime("%Y-%m-%d"),
        "time": when.strftime("%H:%M"),
        "message": "Stand up",
    })
    assert message.startswith("Reminder set")
    assert calls and calls[0][0].startswith("brahma-reminder-")
    assert "schtasks" not in " ".join(calls[0][1])


def test_open_path_uses_xdg_open_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    launched = []

    class _Proc:
        pass

    def _popen(argv, **kwargs):
        launched.append(argv)
        return _Proc()

    monkeypatch.setattr("core.platform_support.which", lambda cmd: "/usr/bin/xdg-open" if cmd == "xdg-open" else None)
    monkeypatch.setattr("core.platform_support.subprocess.Popen", _popen)
    from core.platform_support import open_path

    assert open_path("/tmp/note.txt") is True
    assert launched[0][0].endswith("xdg-open")
    assert launched[0][1] == "/tmp/note.txt"


def test_ota_refuses_exe_on_linux(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    from core.updater_ota import check_for_updates, download_and_apply_update

    assert check_for_updates() is None
    download_and_apply_update("https://example.invalid/setup.exe")
    err = capsys.readouterr().out
    assert "Windows" in err


def test_safe_chromium_flags_without_gpu(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("BRAHMA_DISABLE_GPU", "1")
    from core.webengine_flags import build_chromium_flags

    flags = build_chromium_flags()
    assert "--disable-gpu" in flags
    assert "--ignore-gpu-blocklist" not in flags
    assert "--use-angle=d3d11" not in flags
