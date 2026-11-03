"""Linux (and small cross-platform) desktop helpers.

Windows callers keep their own Win32 code. These functions are the Linux
branch: they prefer the distro tools Ubuntu/Cinnamon actually ships
(xdg-open, notify-send, loginctl, wmctrl, xdotool, pactl/wpctl, playerctl,
espeak-ng, mpv/ffplay) and log a concrete next step when a tool is missing.
Nothing here raises to the caller.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path


_LOGGED: set[str] = set()


def _log(component: str, message: str) -> None:
    print(f"[{component}] {message}")


def _log_once(key: str, component: str, message: str) -> None:
    if key in _LOGGED:
        return
    _LOGGED.add(key)
    _log(component, message)


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def is_windows() -> bool:
    return sys.platform == "win32"


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _run(argv: list[str], timeout: float = 8) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return None
    except Exception as exc:
        _log("Platform", f"{' '.join(argv[:2])} failed: {exc}")
        return None


def open_path(path: str) -> bool:
    """Open a file, folder, or URL with the platform default handler."""
    target = str(path)
    try:
        if is_windows():
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        opener = which("xdg-open")
        if not opener:
            _log("Desktop", f"xdg-open is not installed; cannot open {target}. Install xdg-utils.")
            return False
        subprocess.Popen([opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:
        _log("Desktop", f"Could not open {target}: {exc}")
        return False


def reveal_path(path: str) -> bool:
    """Show a file in the file manager (or open its parent folder)."""
    p = Path(path)
    try:
        if is_windows():
            if p.exists() and p.is_file():
                subprocess.Popen(["explorer.exe", f"/select,{p}"])
            else:
                subprocess.Popen(["explorer.exe", str(p if p.is_dir() else p.parent)])
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
            return True
        parent = p if p.is_dir() else p.parent
        # Cinnamon's file manager is Nemo; xdg-open honors the default.
        return open_path(str(parent))
    except Exception as exc:
        _log("Desktop", f"Could not reveal {path}: {exc}")
        return False


def notify(title: str, body: str) -> bool:
    if not is_linux():
        return False
    sender = which("notify-send")
    if not sender:
        _log("Notify", f"notify-send is not installed; notification not shown: {title}. Install libnotify-bin.")
        return False
    try:
        subprocess.Popen(
            [sender, "--app-name=Brahma Evo", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as exc:
        _log("Notify", f"notify-send failed: {exc}")
        return False


def lock_session() -> bool:
    """Lock the current desktop session. Cinnamon first, then logind."""
    if not is_linux():
        return False
    candidates = [
        ["cinnamon-screensaver-command", "--lock"],
        ["cinnamon-screensaver-command", "-l"],
        ["loginctl", "lock-session"],
        ["xdg-screensaver", "lock"],
        ["gnome-screensaver-command", "-l"],
        ["dm-tool", "lock"],
    ]
    for argv in candidates:
        if not which(argv[0]):
            continue
        result = _run(argv, timeout=6)
        if result is not None and result.returncode == 0:
            _log("Session", f"Locked the session with {argv[0]}.")
            return True
    _log(
        "Session",
        "Could not lock the session. Install cinnamon-screensaver "
        "(cinnamon-screensaver-command --lock) or use a logind seat (loginctl lock-session).",
    )
    return False


def show_desktop() -> bool:
    if which("wmctrl"):
        result = _run(["wmctrl", "-k", "on"])
        if result is not None and result.returncode == 0:
            return True
    _log("Window", "wmctrl is not available; cannot show the desktop. Install wmctrl.")
    return False


def active_window() -> dict:
    """Foreground window title, pid, and geometry. Empty dict fields on failure."""
    info = {"title": "", "class_name": "", "pid": 0, "hwnd": 0, "rect": (0, 0, 0, 0)}
    if not is_linux():
        return info
    if which("xdotool"):
        wid = _run(["xdotool", "getactivewindow"])
        if wid is not None and wid.returncode == 0 and wid.stdout.strip().isdigit():
            window_id = wid.stdout.strip()
            name = _run(["xdotool", "getwindowname", window_id])
            pid = _run(["xdotool", "getwindowpid", window_id])
            geo = _run(["xdotool", "getwindowgeometry", "--shell", window_id])
            title = name.stdout.strip() if name and name.returncode == 0 else ""
            pid_val = 0
            if pid and pid.returncode == 0 and pid.stdout.strip().isdigit():
                pid_val = int(pid.stdout.strip())
            x = y = w = h = 0
            if geo and geo.returncode == 0:
                fields = dict(
                    line.split("=", 1) for line in geo.stdout.splitlines() if "=" in line
                )
                try:
                    x, y = int(fields.get("X", 0)), int(fields.get("Y", 0))
                    w, h = int(fields.get("WIDTH", 0)), int(fields.get("HEIGHT", 0))
                except ValueError:
                    pass
            info.update({
                "title": title,
                "class_name": title,
                "pid": pid_val,
                "hwnd": int(window_id),
                "rect": (x, y, w, h),
                "bbox": (x, y, x + w, y + h),
            })
            return info
    if which("wmctrl"):
        listed = _run(["wmctrl", "-lpG"])
        if listed is not None and listed.returncode == 0:
            for line in listed.stdout.splitlines():
                parts = line.split(None, 8)
                # 0:id 1:desktop 2:pid 3:x 4:y 5:w 6:h 7:host 8:title
                if len(parts) < 9:
                    continue
                # Active window is not marked by -lpG. Fall through.
            active = _run(["wmctrl", "-a", ":ACTIVE:"])
            _ = active
    _log_once(
        "active-window",
        "Window",
        "Cannot read the active window. Install xdotool (preferred) or wmctrl.",
    )
    return info


def focus_window_by_title(fragment: str) -> bool:
    """Raise the first window whose title contains ``fragment``."""
    fragment = (fragment or "").strip()
    if not fragment or not is_linux():
        return False
    if which("wmctrl"):
        listed = _run(["wmctrl", "-l"])
        if listed is not None and listed.returncode == 0:
            needle = fragment.lower()
            for line in listed.stdout.splitlines():
                parts = line.split(None, 3)
                title = parts[3] if len(parts) > 3 else ""
                if needle in title.lower():
                    result = _run(["wmctrl", "-ia", parts[0]])
                    if result is not None and result.returncode == 0:
                        return True
    if which("xdotool"):
        found = _run(["xdotool", "search", "--name", fragment])
        if found is not None and found.returncode == 0:
            for wid in found.stdout.split():
                result = _run(["xdotool", "windowactivate", "--sync", wid])
                if result is not None and result.returncode == 0:
                    return True
    _log("Window", f"Could not focus a window matching '{fragment}'. Install wmctrl or xdotool.")
    return False


def window_geometry_by_title(fragment: str) -> tuple[int, int, int, int] | None:
    if not is_linux() or not which("xdotool"):
        return None
    found = _run(["xdotool", "search", "--name", fragment])
    if found is None or found.returncode != 0:
        return None
    for wid in found.stdout.split():
        geo = _run(["xdotool", "getwindowgeometry", "--shell", wid])
        if geo is None or geo.returncode != 0:
            continue
        fields = dict(line.split("=", 1) for line in geo.stdout.splitlines() if "=" in line)
        try:
            return (
                int(fields.get("X", 0)),
                int(fields.get("Y", 0)),
                int(fields.get("WIDTH", 0)),
                int(fields.get("HEIGHT", 0)),
            )
        except ValueError:
            continue
    return None


def minimize_windows_matching(names: list[str]) -> int:
    """Minimize visible windows whose pid command contains one of ``names``."""
    if not is_linux() or not which("wmctrl"):
        _log("Window", "wmctrl is required to minimize windows on Linux.")
        return 0
    listed = _run(["wmctrl", "-lp"])
    if listed is None or listed.returncode != 0:
        return 0
    needles = tuple(n.lower() for n in names)
    count = 0
    for line in listed.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 3 or not parts[2].isdigit():
            continue
        try:
            import psutil
            cmd = " ".join(psutil.Process(int(parts[2])).cmdline()).lower()
        except Exception:
            cmd = ""
        if any(n in cmd for n in needles):
            result = _run(["wmctrl", "-ir", parts[0], "-b", "add,hidden"])
            if result is not None and result.returncode == 0:
                count += 1
    return count


def idle_seconds() -> float | None:
    """Seconds since the last key or mouse event, or None if it cannot be read."""
    if not is_linux():
        return None
    if which("xprintidle"):
        result = _run(["xprintidle"])
        if result is not None and result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip()) / 1000.0
    via_xss = _idle_via_libxss()
    if via_xss is not None:
        return via_xss
    _log_once(
        "idle",
        "Sensorium",
        "User idle time is unavailable. Install xprintidle or libxss1. "
        "Idle-based prompts will treat the user as active.",
    )
    return None


def _idle_via_libxss() -> float | None:
    try:
        import ctypes
        x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
        xss = ctypes.cdll.LoadLibrary("libXss.so.1")
    except Exception:
        return None
    try:
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
        x11.XDefaultScreen.restype = ctypes.c_int
        x11.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XRootWindow.restype = ctypes.c_ulong
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xss.XScreenSaverAllocInfo.restype = ctypes.c_void_p
        xss.XScreenSaverQueryInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
        ]
        xss.XScreenSaverQueryInfo.restype = ctypes.c_int
        display = x11.XOpenDisplay(None)
        if not display:
            return None
        try:
            screen = x11.XDefaultScreen(display)
            root = x11.XRootWindow(display, screen)
            info = xss.XScreenSaverAllocInfo()
            if not info or not xss.XScreenSaverQueryInfo(display, root, info):
                return None
            # XScreenSaverInfo.idle is an unsigned long at the end of the struct.
            # Layout: window, state, kind, since, idle, event_mask.
            class _Info(ctypes.Structure):
                _fields_ = [
                    ("window", ctypes.c_ulong),
                    ("state", ctypes.c_int),
                    ("kind", ctypes.c_int),
                    ("til_or_since", ctypes.c_ulong),
                    ("idle", ctypes.c_ulong),
                    ("event_mask", ctypes.c_ulong),
                ]
            parsed = ctypes.cast(info, ctypes.POINTER(_Info)).contents
            return max(0.0, parsed.idle / 1000.0)
        finally:
            x11.XCloseDisplay(display)
    except Exception:
        return None


def _audio_tool() -> str | None:
    if which("pactl"):
        return "pactl"
    if which("wpctl"):
        return "wpctl"
    return None


def linux_volume(action: str, value: int | None = None) -> int | None:
    """Master volume via PulseAudio (pactl) or PipeWire (wpctl).

    ``action`` is get, set, up, down, or mute. ``get`` returns 0-100 or None.
    """
    tool = _audio_tool()
    if tool is None:
        _log("Audio", "Neither pactl nor wpctl is installed. Install pulseaudio-utils (PipeWire ships pactl too).")
        return None
    try:
        if tool == "pactl":
            if action == "get":
                result = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
                if result is None:
                    return None
                match = re.search(r"(\d+)%", result.stdout)
                return int(match.group(1)) if match else None
            if action == "set" and value is not None:
                _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{int(value)}%"])
            elif action == "up":
                _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"])
            elif action == "down":
                _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"])
            elif action == "mute":
                _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
            return None
        # wpctl volumes are linear 0.0-1.0 (values above 1.0 are allowed).
        if action == "get":
            result = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
            if result is None:
                return None
            match = re.search(r"([0-9.]+)", result.stdout)
            return max(0, min(100, round(float(match.group(1)) * 100))) if match else None
        if action == "set" and value is not None:
            _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{max(0, min(100, int(value))) / 100:.2f}"])
        elif action == "up":
            _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%+"])
        elif action == "down":
            _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"])
        elif action == "mute":
            _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])
    except Exception as exc:
        _log("Audio", f"Volume control failed: {exc}")
    return None


def linux_source_volume(action: str, value: int | None = None) -> int | None:
    """Default microphone volume, 0-100. Used to duck/restore the mic on a call."""
    if which("pactl"):
        if action == "get":
            result = _run(["pactl", "get-source-volume", "@DEFAULT_SOURCE@"])
            if result is None:
                return None
            match = re.search(r"(\d+)%", result.stdout or "")
            return int(match.group(1)) if match else None
        if action == "set" and value is not None:
            _run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", f"{int(value)}%"])
            _run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0"])
        return None
    if which("wpctl"):
        if action == "get":
            result = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"])
            if result is None:
                return None
            match = re.search(r"([0-9.]+)", result.stdout or "")
            return max(0, min(100, round(float(match.group(1)) * 100))) if match else None
        if action == "set" and value is not None:
            _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", f"{max(0, min(100, int(value))) / 100:.2f}"])
            _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0"])
        return None
    _log("Audio", "Cannot change microphone volume without pactl or wpctl.")
    return None


def set_linux_app_volume(process_names: tuple[str, ...], level: float) -> bool:
    """Set the Pulse/PipeWire stream volume for processes in ``process_names``.

    ``level`` is 0.0-1.0. This is the Linux stand-in for per-app WASAPI volume.
    """
    if not which("pactl"):
        _log("Audio", "Per-app volume needs pactl (pulseaudio-utils). PipeWire's pactl works.")
        return False
    listed = _run(["pactl", "list", "sink-inputs"], timeout=6)
    if listed is None or listed.returncode != 0:
        return False
    wanted = tuple(n.lower() for n in process_names)
    current_id = None
    matched: list[str] = []
    blob = ""
    for line in (listed.stdout or "").splitlines():
        if line.startswith("Sink Input #"):
            if current_id and any(n in blob for n in wanted):
                matched.append(current_id)
            current_id = line.split("#", 1)[1].strip()
            blob = ""
        else:
            blob += line.lower() + "\n"
    if current_id and any(n in blob for n in wanted):
        matched.append(current_id)
    if not matched:
        _log("Audio", f"No Pulse stream matched {process_names}; per-app volume left unchanged.")
        return False
    percent = f"{max(0, min(150, round(level * 100)))}%"
    ok = False
    for sink_id in matched:
        result = _run(["pactl", "set-sink-input-volume", sink_id, percent])
        ok = ok or (result is not None and result.returncode == 0)
    return ok


def linux_media_key(key_name: str) -> bool:
    """MPRIS via playerctl, with pactl/wpctl for volume keys."""
    name = (key_name or "").lower()
    player = {
        "playpause": ["playerctl", "play-pause"],
        "play": ["playerctl", "play"],
        "pause": ["playerctl", "pause"],
        "nexttrack": ["playerctl", "next"],
        "next": ["playerctl", "next"],
        "prevtrack": ["playerctl", "previous"],
        "prev": ["playerctl", "previous"],
        "previous": ["playerctl", "previous"],
    }.get(name)
    if player:
        if not which("playerctl"):
            _log("Music", "playerctl is not installed. Install it for MPRIS play/pause/next (sudo apt install playerctl).")
            return False
        result = _run(player)
        if result is not None and result.returncode == 0:
            return True
        _log("Music", f"playerctl {' '.join(player[1:])} failed. Is a player running with MPRIS?")
        return False
    if name in {"volumeup", "volumedown", "volumemute", "mute"}:
        action = {"volumeup": "up", "volumedown": "down"}.get(name, "mute")
        linux_volume(action)
        return _audio_tool() is not None
    return False


def power_profile_get() -> str | None:
    if not is_linux():
        return None
    if not which("powerprofilesctl"):
        _log(
            "Power",
            "powerprofilesctl is not installed. Power profiles stay unchanged. "
            "Install power-profiles-daemon if you want performance/balanced/power-saver.",
        )
        return None
    result = _run(["powerprofilesctl", "get"])
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def power_profile_set(profile: str) -> bool:
    if not is_linux():
        return False
    if not which("powerprofilesctl"):
        _log("Power", f"Cannot switch to '{profile}' without powerprofilesctl (package power-profiles-daemon).")
        return False
    result = _run(["powerprofilesctl", "set", profile])
    if result is not None and result.returncode == 0:
        _log("Power", f"Power profile set to {profile}.")
        return True
    detail = (result.stderr or result.stdout).strip() if result else "no response"
    _log("Power", f"powerprofilesctl set {profile} failed: {detail}")
    return False


def find_steam_linux() -> Path | None:
    candidates = [
        Path.home() / ".steam" / "steam",
        Path.home() / ".local" / "share" / "Steam",
        Path.home() / ".steam" / "root",
        Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
        Path("/usr/lib/steam"),
    ]
    for path in candidates:
        if (path / "steamapps").is_dir() or (path / "steam.sh").is_file():
            return path
    return None


def process_running(names: tuple[str, ...]) -> bool:
    try:
        import psutil
        needles = tuple(n.lower() for n in names)
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if any(n in name for n in needles):
                return True
    except Exception as exc:
        _log("Process", f"Process scan failed: {exc}")
    return False


def play_audio_file(path: str, wait: bool = True) -> subprocess.Popen | bool | None:
    """Play a sound file. Returns a Popen when ``wait`` is False, else True/False/None."""
    players = []
    if which("mpv"):
        players.append(["mpv", "--no-video", "--really-quiet", path])
    if which("ffplay"):
        players.append(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path])
    if which("pw-play"):
        players.append(["pw-play", path])
    if which("paplay"):
        players.append(["paplay", path])
    if which("aplay"):
        players.append(["aplay", "-q", path])
    if not players:
        _log(
            "Audio",
            f"No player for {path}. Install mpv (recommended) or ffmpeg (ffplay). "
            "paplay/pw-play only handle WAV/OGG.",
        )
        return None
    for argv in players:
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not wait:
                return proc
            proc.wait(timeout=180)
            if proc.returncode == 0:
                return True
        except Exception as exc:
            _log("Audio", f"{argv[0]} failed: {exc}")
            continue
    _log("Audio", f"Every audio player failed for {path}.")
    return False


def speak_offline(text: str) -> bool:
    """Offline speech. espeak-ng first, then espeak, speech-dispatcher, then piper."""
    text = (text or "").strip()
    if not text:
        return False
    if which("espeak-ng"):
        result = _run(["espeak-ng", "-v", "en+m3", "-s", "150", text], timeout=120)
        if result is not None and result.returncode == 0:
            return True
    if which("espeak"):
        result = _run(["espeak", "-v", "en+m3", "-s", "150", text], timeout=120)
        if result is not None and result.returncode == 0:
            return True
    if which("spd-say"):
        result = _run(["spd-say", "-w", text], timeout=120)
        if result is not None and result.returncode == 0:
            return True
    model = os.environ.get("BRAHMA_PIPER_MODEL", "").strip()
    if which("piper") and model and Path(model).is_file():
        try:
            proc = subprocess.run(
                ["piper", "--model", model, "--output-raw"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=120,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout and which("aplay"):
                play = subprocess.run(
                    ["aplay", "-q", "-r", "22050", "-f", "S16_LE", "-t", "raw"],
                    input=proc.stdout,
                    timeout=120,
                    check=False,
                )
                return play.returncode == 0
        except Exception as exc:
            _log("TTS", f"piper failed: {exc}")
    _log(
        "TTS",
        "No offline speech engine is available. Install espeak-ng "
        "(sudo apt install espeak-ng). For a neural voice, install piper and set BRAHMA_PIPER_MODEL.",
    )
    return False


def restore_from_trash(original: Path) -> str | None:
    """Move a file back out of the FreeDesktop trash, if we can identify it."""
    info_dir = Path.home() / ".local" / "share" / "Trash" / "info"
    files_dir = Path.home() / ".local" / "share" / "Trash" / "files"
    if not info_dir.is_dir():
        _log("Trash", "No FreeDesktop trash at ~/.local/share/Trash.")
        return None
    wanted = str(original)
    for info in info_dir.glob("*.trashinfo"):
        try:
            text = info.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        trashed = ""
        for line in text.splitlines():
            if line.startswith("Path="):
                trashed = urllib.parse.unquote(line.split("=", 1)[1].strip())
                break
        if not trashed:
            continue
        trashed_path = Path(trashed)
        if trashed != wanted and not (
            trashed_path.name == original.name and trashed_path.parent == original.parent
        ):
            continue
        src = files_dir / info.name[: -len(".trashinfo")]
        if not src.exists():
            continue
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            if original.exists():
                return None
            shutil.move(str(src), str(original))
            info.unlink(missing_ok=True)
            return f"'{original.name}' restored from the Trash."
        except Exception as exc:
            _log("Trash", f"Restore failed for {original}: {exc}")
            return None
    _log("Trash", f"'{original.name}' was not found in the Trash by its original path.")
    return None


def autostart_desktop_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "autostart" / "brahma-evo.desktop"


def autostart_enabled() -> bool:
    path = autostart_desktop_path()
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if line.strip().lower().startswith("x-gnome-autostart-enabled="):
            return line.split("=", 1)[1].strip().lower() == "true"
        if line.strip().lower() == "hidden=true":
            return False
    return True


def set_autostart(enabled: bool, exec_line: str, icon: str | None = None) -> bool:
    path = autostart_desktop_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not enabled:
            if path.exists():
                path.unlink()
            _log("Autostart", f"Removed {path}.")
            return True
        icon_line = f"Icon={icon}\n" if icon else ""
        path.write_text(
            "\n".join([
                "[Desktop Entry]",
                "Type=Application",
                "Version=1.0",
                "Name=Brahma Evo",
                "Comment=Autonomous AI desktop assistant",
                f"Exec={exec_line}",
                icon_line.rstrip("\n"),
                "Terminal=false",
                "Categories=Utility;",
                "X-GNOME-Autostart-enabled=true",
                "StartupNotify=false",
                "",
            ]),
            encoding="utf-8",
        )
        _log("Autostart", f"Wrote {path}.")
        return True
    except Exception as exc:
        _log("Autostart", f"Could not update {path}: {exc}")
        return False


def install_user_timer(
    unit: str,
    when: datetime,
    command: list[str],
    description: str,
    on_calendar: str | None = None,
) -> tuple[bool, str]:
    """Install a systemd --user timer. ``on_calendar`` overrides the one-shot timestamp."""
    if not which("systemctl"):
        message = "systemctl is not available, so the timer was not installed."
        _log("Timer", message)
        return False, message
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    unit_dir = (Path(config_home).expanduser() if config_home else Path.home() / ".config") / "systemd" / "user"
    try:
        unit_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        message = f"Cannot create {unit_dir}: {exc}"
        _log("Timer", message)
        return False, message
    calendar = on_calendar or when.strftime("%Y-%m-%d %H:%M:%S")
    service = unit_dir / f"{unit}.service"
    timer = unit_dir / f"{unit}.timer"
    exec_line = " ".join(_shell_quote(part) for part in command)
    service.write_text(
        "\n".join([
            "[Unit]",
            f"Description={description}",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart={exec_line}",
            "",
        ]),
        encoding="utf-8",
    )
    timer.write_text(
        "\n".join([
            "[Unit]",
            f"Description={description}",
            "",
            "[Timer]",
            f"OnCalendar={calendar}",
            "AccuracySec=1s",
            "Persistent=true",
            "Unit=" + unit + ".service",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]),
        encoding="utf-8",
    )
    reload = _run(["systemctl", "--user", "daemon-reload"], timeout=20)
    if reload is None or reload.returncode != 0:
        detail = (reload.stderr or reload.stdout or "").strip() if reload else "systemctl missing"
        message = (
            "systemd --user is not running, so the timer unit was written but not started. "
            f"({detail}) Start a user systemd session or run: systemctl --user enable --now {unit}.timer"
        )
        _log("Timer", message)
        return False, message
    enable = _run(["systemctl", "--user", "enable", "--now", f"{unit}.timer"], timeout=20)
    if enable is None or enable.returncode != 0:
        detail = (enable.stderr or enable.stdout or "").strip() if enable else ""
        message = f"Could not enable {unit}.timer. {detail}".strip()
        _log("Timer", message)
        return False, message
    return True, f"Timer {unit} set for {calendar}."


def remove_user_timer(unit: str) -> bool:
    if which("systemctl"):
        _run(["systemctl", "--user", "disable", "--now", f"{unit}.timer"], timeout=20)
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    unit_dir = (Path(config_home).expanduser() if config_home else Path.home() / ".config") / "systemd" / "user"
    removed = False
    for suffix in (".timer", ".service"):
        path = unit_dir / f"{unit}{suffix}"
        if path.exists():
            path.unlink()
            removed = True
    if which("systemctl"):
        _run(["systemctl", "--user", "daemon-reload"], timeout=20)
    return removed


def _shell_quote(value: str) -> str:
    if not value:
        return "''"
    if re.fullmatch(r"[A-Za-z0-9_./:=+-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"
