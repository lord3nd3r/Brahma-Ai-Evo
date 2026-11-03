"""Qt WebEngine / Chromium flags.

Windows keeps the historical GPU string, including ANGLE/D3D11. Linux does not
force ``--enable-gpu-rasterization`` or ``--ignore-gpu-blocklist`` unless a
real GPU is usable. Those two flags crash Chromium when the process is on
Xvfb, llvmpipe, or a box with no DRM render node. A detected GPU (the Ryzen
Vega case) still gets WebGL and GPU rasterization, without ignoring Chromium's
GPU blocklist. Set ``BRAHMA_IGNORE_GPU_BLOCKLIST=1`` to opt into that flag, or
``BRAHMA_FORCE_GPU=1`` / ``BRAHMA_DISABLE_GPU=1`` to override detection.

If ``QTWEBENGINE_CHROMIUM_FLAGS`` is already set, it is left alone.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Exact historical Windows string from main.py. Do not reorder.
WINDOWS_CHROMIUM_FLAGS = (
    "--enable-gpu-rasterization --enable-zero-copy --ignore-gpu-blocklist "
    "--enable-accelerated-2d-canvas --enable-webgl --enable-webgl2-compute-context "
    "--disable-frame-rate-limit --disable-gpu-vsync --num-raster-threads=4 "
    "--use-angle=d3d11 --disable-gpu-driver-bug-workarounds"
)

_APPLIED = False


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _display_is_xvfb() -> bool:
    display = os.environ.get("DISPLAY", "").strip()
    if not display:
        return False
    number = display.split(":")[-1].split(".")[0]
    try:
        out = subprocess.check_output(["ps", "-eo", "args"], text=True, timeout=2)
    except Exception:
        return False
    for line in out.splitlines():
        if "Xvfb" not in line and "xvfb" not in line:
            continue
        if f":{number}" in line:
            return True
    return False


def linux_gpu_usable() -> bool:
    """True when Linux should ask Chromium to use the GPU."""
    if not sys.platform.startswith("linux"):
        return sys.platform == "win32"
    if _env_flag("BRAHMA_DISABLE_GPU"):
        return False
    if _env_flag("BRAHMA_FORCE_GPU"):
        return True
    if os.environ.get("LIBGL_ALWAYS_SOFTWARE", "").strip() not in {"", "0"}:
        return False
    if _display_is_xvfb():
        return False
    dri = Path("/dev/dri")
    if not dri.is_dir():
        return False
    return any(dri.glob("renderD*")) or any(dri.glob("card*"))


def build_chromium_flags() -> str:
    """Return the flag string for this platform. Does not touch the environment."""
    if sys.platform == "win32":
        return WINDOWS_CHROMIUM_FLAGS
    if sys.platform == "darwin":
        return (
            "--enable-gpu-rasterization --enable-zero-copy --ignore-gpu-blocklist "
            "--enable-accelerated-2d-canvas --enable-webgl --enable-webgl2-compute-context "
            "--disable-frame-rate-limit --disable-gpu-vsync --num-raster-threads=4 "
            "--disable-gpu-driver-bug-workarounds"
        )
    if not sys.platform.startswith("linux"):
        return (
            "--enable-webgl --enable-accelerated-2d-canvas --num-raster-threads=4"
        )

    common = "--no-sandbox --disable-dev-shm-usage"
    if not linux_gpu_usable():
        # Software path: do not start a GPU process that has nothing to attach to.
        return f"--disable-gpu --disable-gpu-compositing {common}"

    accelerated = (
        "--enable-gpu-rasterization --enable-accelerated-2d-canvas "
        "--enable-webgl --enable-webgl2-compute-context --num-raster-threads=4 "
        f"{common}"
    )
    if _env_flag("BRAHMA_IGNORE_GPU_BLOCKLIST"):
        accelerated = "--ignore-gpu-blocklist " + accelerated
    return accelerated


def _ensure_xdg_runtime_dir() -> None:
    """Qt and Pulse want XDG_RUNTIME_DIR. A Cinnamon session sets it; a bare shell may not."""
    if not sys.platform.startswith("linux"):
        return
    if os.environ.get("XDG_RUNTIME_DIR", "").strip():
        return
    runtime = Path(f"/tmp/brahma-runtime-{os.getuid()}")
    try:
        runtime.mkdir(mode=0o700, exist_ok=True)
        os.chmod(runtime, 0o700)
    except Exception as exc:
        print(f"[Platform] Could not create an XDG runtime dir: {exc}")
        return
    os.environ["XDG_RUNTIME_DIR"] = str(runtime)
    print(f"[Platform] XDG_RUNTIME_DIR was unset. Using {runtime}.")


def prefer_pyqt_platform_plugins() -> None:
    """OpenCV's wheel ships its own Qt plugins and points Qt at them.

    On Linux that plugin set does not load against the system libxcb stack, so
    QApplication aborts before the window exists. Point Qt back at PyQt6 when
    the path is OpenCV's. A user-set path that is not OpenCV is left alone.
    Windows is untouched.
    """
    if not sys.platform.startswith("linux"):
        return
    current = os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH", "")
    if current and "cv2" not in current.replace("\\", "/"):
        return
    try:
        import PyQt6
        plugins = Path(PyQt6.__file__).resolve().parent / "Qt6" / "plugins"
        if not plugins.is_dir():
            print(f"[Qt] PyQt6 plugins not found at {plugins}.")
            return
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins)
        # cv2 also exports QT_PLUGIN_PATH in some builds.
        qt_plugin = os.environ.get("QT_PLUGIN_PATH", "")
        if "cv2" in qt_plugin.replace("\\", "/"):
            os.environ["QT_PLUGIN_PATH"] = str(plugins)
        print("[Qt] Using PyQt6 platform plugins. OpenCV had pointed Qt at its own plugin directory.")
    except Exception as exc:
        print(f"[Qt] Could not select PyQt6 platform plugins: {exc}")


def apply_webengine_flags() -> str:
    """Set ``QTWEBENGINE_CHROMIUM_FLAGS`` once, unless the user already did."""
    global _APPLIED
    _ensure_xdg_runtime_dir()
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    if _APPLIED:
        return existing
    if existing:
        _APPLIED = True
        return existing
    flags = build_chromium_flags()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags
    if sys.platform.startswith("linux") and not linux_gpu_usable():
        os.environ.setdefault("QT_OPENGL", "software")
        print(
            "[WebEngine] No usable GPU detected (software session or no DRM node). "
            "Chromium GPU flags are off so Qt WebEngine can start. "
            "Set BRAHMA_FORCE_GPU=1 to opt into GPU rasterization."
        )
    elif sys.platform.startswith("linux"):
        print(
            "[WebEngine] Linux GPU detected. WebGL and GPU rasterization are enabled. "
            "--ignore-gpu-blocklist is off (set BRAHMA_IGNORE_GPU_BLOCKLIST=1 to force it)."
        )
    _APPLIED = True
    return flags
