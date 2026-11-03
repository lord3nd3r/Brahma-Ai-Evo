"""Startup briefing is spoken once, and stop-speaking reaches native playback."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtWidgets import QDialog, QLineEdit, QWidget

from main import (
    BrahmaLive,
    claim_startup_briefing,
    echo_tail_seconds,
    reset_startup_briefing_guard,
    speech_is_duplicate,
    _speak_daily_briefing,
)
from ui import apply_stop_button_state, escape_should_stop_speech
from PyQt6.QtWidgets import QApplication, QPushButton


def test_identical_speech_is_deduped_for_sixty_seconds():
    history = [("good morning sir", 0.0)]
    assert speech_is_duplicate(history, "Good   morning sir", now=30.0) is True
    assert speech_is_duplicate(history, "Good morning sir", now=61.0) is False
    assert speech_is_duplicate(history, "A different line", now=10.0) is False


def test_linux_echo_tail_is_long_enough_for_speaker_reverb():
    import sys
    if sys.platform.startswith("linux"):
        assert echo_tail_seconds() == 1.0
    else:
        assert echo_tail_seconds() == 0.35


def test_startup_briefing_is_not_spoken_twice(monkeypatch):
    reset_startup_briefing_guard()
    calls = []

    class FakeUI:
        def show_daily_briefing(self, data):
            calls.append(("show", data))

        def write_log(self, message):
            calls.append(("log", message))

    monkeypatch.setattr(
        "actions.daily_briefing.compile_unified_briefing",
        lambda *a, **k: ({"greeting": "Good morning"}, "Good morning, sir."),
    )
    spoken = []
    _speak_daily_briefing(FakeUI(), spoken.append)
    _speak_daily_briefing(FakeUI(), spoken.append)
    assert spoken == ["Good morning, sir."]
    assert [item for item in calls if item[0] == "log"] == [("log", "Brahma Evo: Good morning, sir.")]


def test_briefing_claim_window_blocks_a_second_caller():
    reset_startup_briefing_guard()
    assert claim_startup_briefing(now=1000.0) is True
    assert claim_startup_briefing(now=1010.0) is False
    assert claim_startup_briefing(now=1100.0) is True


def test_trigger_barge_in_stops_native_playback_and_flushes_audio():
    live = object.__new__(BrahmaLive)
    live._speaking_lock = threading.Lock()
    live._is_speaking = True
    live._server_turn_active = False
    live._discard_server_audio = False
    live._scripted_delivery_active = True
    live._last_spoke_time = 0.0

    class _Queue:
        def __init__(self):
            self.items = ["chunk"]

        def empty(self):
            return not self.items

        def get_nowait(self):
            return self.items.pop()

    live.audio_in_queue = _Queue()
    states = []
    live.ui = SimpleNamespace(muted=False, set_state=states.append)

    with (
        patch("actions.attention_monitor.stop_native_speech") as stop,
        patch("core.live_voice_engine.LiveVoiceEngine.get_instance", side_effect=RuntimeError("no engine")),
        patch("sound_manager.SoundManager.instance", side_effect=RuntimeError("no sound")),
    ):
        live.trigger_barge_in()

    stop.assert_called_once()
    assert live.audio_in_queue.empty()
    assert live._is_speaking is False
    assert states == ["LISTENING"]


def test_escape_does_not_stop_speech_from_inside_a_dialog():
    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    field = QLineEdit(dialog)
    assert escape_should_stop_speech(field) is False
    plain = QWidget()
    assert escape_should_stop_speech(plain) is True
    assert escape_should_stop_speech(None) is True
    dialog.deleteLater()
    plain.deleteLater()
    app.processEvents()


def test_stop_button_is_enabled_only_while_speaking():
    app = QApplication.instance() or QApplication([])
    button = QPushButton("■")
    apply_stop_button_state(button, False)
    assert button.isEnabled() is False
    apply_stop_button_state(button, True)
    assert button.isEnabled() is True
    assert "255, 59, 48" in button.styleSheet()
    button.deleteLater()
    app.processEvents()
