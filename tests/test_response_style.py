"""Response-style presets stay short and do not change the default prompt."""

from __future__ import annotations

from core import response_style
from core.llm_providers import get_preset
from core.response_style import (
    PRESET_TEXT,
    PROVIDER_STYLE_DEFAULTS,
    RIGOR_TEXT,
    STYLE_RIGOR,
    STYLE_WARM,
    WARM_TEXT,
    apply_style_to_messages,
    compose_system_prompt,
    resolved_style_id,
    word_count,
)


TOOL_LINE = "When the user asks for an action, call the matching tool."
BASE = f"You are Brahma Evo, a concise desktop assistant.\n{TOOL_LINE}"


def _settings(monkeypatch, data):
    monkeypatch.setattr(response_style.config_manager, "load_settings", lambda: dict(data))


def test_builtin_presets_are_short_labeled_chunks():
    assert word_count(RIGOR_TEXT) <= 150
    assert word_count(WARM_TEXT) <= 150
    assert word_count(RIGOR_TEXT) > 40
    for text in (RIGOR_TEXT, WARM_TEXT):
        assert "Identity:" in text
        assert "Tools:" in text
    lowered = RIGOR_TEXT.lower()
    assert "assumption" not in lowered
    assert "proceed" not in lowered
    assert "i'm not sure" in lowered
    assert "lead with the answer" in lowered
    assert "working code first" in lowered
    assert "it depends" in WARM_TEXT.lower()
    assert PRESET_TEXT["none"] == ""
    assert PROVIDER_STYLE_DEFAULTS["ollama"] == STYLE_RIGOR
    assert PROVIDER_STYLE_DEFAULTS["llamacpp"] == STYLE_RIGOR


def test_missing_setting_keeps_todays_prompt_except_local_providers(monkeypatch):
    _settings(monkeypatch, {})
    assert resolved_style_id("grok") == "none"
    assert resolved_style_id("openrouter") == "none"
    assert resolved_style_id("gemini") == "none"
    assert resolved_style_id("local") == "none"
    assert compose_system_prompt(BASE, provider_id="grok") == BASE
    assert compose_system_prompt(BASE, provider_id="gemini") is BASE or compose_system_prompt(BASE, provider_id="gemini") == BASE
    assert resolved_style_id("ollama") == "rigor"
    assert resolved_style_id("llamacpp") == "rigor"
    ollama = compose_system_prompt(BASE, provider_id="ollama")
    assert ollama.startswith(PRESET_TEXT["rigor"])
    assert TOOL_LINE in ollama
    assert ollama.index(PRESET_TEXT["rigor"]) < ollama.index(TOOL_LINE)


def test_global_choice_and_provider_override(monkeypatch):
    _settings(monkeypatch, {"response_style": "warm"})
    assert resolved_style_id("grok") == "warm"
    assert resolved_style_id("ollama") == "warm"
    warm = compose_system_prompt(BASE, provider_id="openrouter")
    assert warm.startswith(PRESET_TEXT["warm"])
    assert TOOL_LINE in warm

    _settings(monkeypatch, {"response_style": "warm", "response_style_grok": "rigor"})
    assert resolved_style_id("grok") == "rigor"
    assert resolved_style_id("openrouter") == "warm"

    _settings(monkeypatch, {"response_style": "rigor", "response_style_ollama": "none"})
    assert resolved_style_id("ollama") == "none"
    assert compose_system_prompt(BASE, provider_id="ollama") == BASE


def test_custom_prompt_is_optional(monkeypatch):
    _settings(monkeypatch, {"response_style": "custom", "response_style_custom": "Tone: Be brief.\n\nTools: Call a tool for actions."})
    composed = compose_system_prompt(BASE, provider_id="grok")
    assert composed.startswith("Tone: Be brief.")
    assert TOOL_LINE in composed

    _settings(monkeypatch, {
        "response_style": "custom",
        "response_style_custom": "Global custom.",
        "response_style_ollama": "custom",
        "response_style_custom_ollama": "Local custom.",
    })
    assert compose_system_prompt("Base.", provider_id="ollama").startswith("Local custom.")
    assert compose_system_prompt("Base.", provider_id="grok").startswith("Global custom.")

    _settings(monkeypatch, {"response_style": "custom", "response_style_custom": "   "})
    assert compose_system_prompt(BASE, provider_id="grok") == BASE


def test_style_is_not_applied_twice_and_empty_messages_gain_a_system_turn(monkeypatch):
    _settings(monkeypatch, {"response_style": "rigor"})
    once = apply_style_to_messages(
        [{"role": "system", "content": BASE}, {"role": "user", "content": "hi"}],
        "grok",
    )
    twice = apply_style_to_messages(once, "grok")
    assert once[0]["content"].count("Identity:") == 1
    assert twice[0]["content"] == once[0]["content"]
    assert TOOL_LINE in twice[0]["content"]

    _settings(monkeypatch, {})
    original = [{"role": "user", "content": "hi"}]
    assert apply_style_to_messages(original, "grok") is original
    styled = apply_style_to_messages(original, get_preset("ollama").id)
    assert styled[0]["role"] == "system"
    assert "Identity:" in styled[0]["content"]
    assert styled[1]["content"] == "hi"
