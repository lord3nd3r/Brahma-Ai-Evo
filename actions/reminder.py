# actions/reminder.py

import subprocess
import os
import sys
from datetime import datetime
from pathlib import Path


def _schedule_linux_reminder(target_dt: datetime, safe_message: str) -> str:
    """One-shot systemd --user timer plus notify-send."""
    from core.platform_support import install_user_timer
    from core.user_paths import get_user_state_dir

    stamp = target_dt.strftime("%Y%m%d_%H%M")
    script_dir = get_user_state_dir() / "reminders"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / f"reminder_{stamp}.py"
    script_path.write_text(
        "\n".join([
            "import shutil, subprocess, sys",
            f"message = {safe_message!r}",
            "title = 'Brahma Reminder'",
            "if shutil.which('notify-send'):",
            "    subprocess.run(['notify-send', '--app-name=Brahma Evo', title, message])",
            "else:",
            "    print('[Reminder] notify-send is not installed:', message, file=sys.stderr)",
            "sound = '/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga'",
            "if shutil.which('paplay'):",
            "    subprocess.run(['paplay', sound])",
            "elif shutil.which('canberra-gtk-play'):",
            "    subprocess.run(['canberra-gtk-play', '-i', 'dialog-information'])",
            "elif shutil.which('espeak-ng'):",
            "    subprocess.run(['espeak-ng', '-v', 'en+m3', message])",
            "else:",
            "    print('[Reminder] No sound player (paplay, canberra-gtk-play, or espeak-ng).', file=sys.stderr)",
            "try:",
            "    import os",
            "    os.remove(__file__)",
            "except Exception:",
            "    pass",
            "",
        ]),
        encoding="utf-8",
    )
    ok, detail = install_user_timer(
        f"brahma-reminder-{stamp}",
        target_dt,
        [sys.executable, str(script_path)],
        f"Brahma reminder: {safe_message}",
    )
    if not ok:
        return f"I couldn't schedule the reminder. {detail}"
    return f"Reminder set for {target_dt.strftime('%B %d at %I:%M %p')}."


def reminder(
    parameters: dict,
    response: str | None = None,
    player=None,
    session_memory=None
) -> str:
    """
    Sets a timed reminder using Windows Task Scheduler.

    parameters:
        - date    (str) YYYY-MM-DD
        - time    (str) HH:MM
        - message (str)

    Returns a result string — Live API voices it automatically.
    No edge_speak needed.
    """

    date_str = parameters.get("date")
    time_str = parameters.get("time")
    message  = parameters.get("message", "Reminder")

    if not date_str or not time_str:
        return "I need both a date and a time to set a reminder."

    try:
        target_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")

        if target_dt <= datetime.now():
            return "That time is already in the past."

        safe_message = message.replace('"', '').replace("'", "").strip()[:200]
        if sys.platform.startswith("linux"):
            result_text = _schedule_linux_reminder(target_dt, safe_message)
            if player and result_text.startswith("Reminder set"):
                player.write_log(f"[reminder] set for {date_str} {time_str}")
            return result_text

        task_name    = f"MARKReminder_{target_dt.strftime('%Y%m%d_%H%M')}"
        safe_message = message.replace('"', '').replace("'", "").strip()[:200]

        python_exe = sys.executable
        if python_exe.lower().endswith("python.exe"):
            pythonw = python_exe.replace("python.exe", "pythonw.exe")
            if os.path.exists(pythonw):
                python_exe = pythonw

        temp_dir      = os.environ.get("TEMP", "C:\\Temp")
        notify_script = os.path.join(temp_dir, f"{task_name}.pyw")
        project_root  = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..")
        )

        script_code = f'''import sys, os, time
sys.path.insert(0, r"{project_root}")

try:
    import winsound
    for freq in [800, 1000, 1200]:
        winsound.Beep(freq, 200)
        time.sleep(0.1)
except Exception:
    pass

try:
    from win10toast import ToastNotifier
    ToastNotifier().show_toast(
        "MARK Reminder",
        "{safe_message}",
        duration=15,
        threaded=False
    )
except Exception:
    try:
        import subprocess
        subprocess.run(["msg", "*", "/TIME:30", "{safe_message}"], shell=True)
    except Exception:
        pass

time.sleep(3)
try:
    os.remove(__file__)
except Exception:
    pass
'''
        with open(notify_script, "w", encoding="utf-8") as f:
            f.write(script_code)

        xml_content = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>MARK Reminder: {safe_message}</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>"{notify_script}"</Arguments>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Principals>
    <Principal>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
</Task>'''

        xml_path = os.path.join(temp_dir, f"{task_name}.xml")
        with open(xml_path, "w", encoding="utf-16") as f:
            f.write(xml_content)

        result = subprocess.run(
            f'schtasks /Create /TN "{task_name}" /XML "{xml_path}" /F',
            shell=True, capture_output=True, text=True
        )

        try:
            os.remove(xml_path)
        except Exception:
            pass

        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip()
            print(f"[Reminder] ❌ schtasks failed: {err}")
            try:
                os.remove(notify_script)
            except Exception:
                pass
            return "I couldn't schedule the reminder due to a system error."

        if player:
            player.write_log(f"[reminder] set for {date_str} {time_str}")

        return f"Reminder set for {target_dt.strftime('%B %d at %I:%M %p')}."

    except ValueError:
        return "I couldn't understand that date or time format."

    except Exception as e:
        return f"Something went wrong while scheduling the reminder: {str(e)[:80]}"