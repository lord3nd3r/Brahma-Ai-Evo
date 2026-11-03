"""OpenAI-compatible provider selection, tool translation, and Grok fallback."""

from __future__ import annotations

import json

import pytest

from core import llm_providers
from core.llm_providers import (
    ProviderCallError,
    chat_completion,
    choose_default_model,
    gemini_declarations_to_openai_tools,
    get_preset,
    grok_failure_notice,
    provider_id_from_setting,
    uses_gemini_live_for_text,
)


def test_grok_preset_is_openai_compatible_xai():
    grok = get_preset("grok")
    assert grok.base_url == "https://api.x.ai/v1"
    assert grok.key_field == "xai_api_key"
    assert grok.requires_key is True
    assert get_preset("ollama").base_url == "http://localhost:11434/v1"
    assert get_preset("llamacpp").requires_key is False
    assert provider_id_from_setting("Grok (xAI)") == "grok"
    assert provider_id_from_setting("OpenRouter") == "openrouter"
    assert provider_id_from_setting("Gemini") == "gemini"


def test_gemini_live_is_not_used_for_grok_text():
    assert uses_gemini_live_for_text("Gemini", session_connected=True, offline=False) is True
    assert uses_gemini_live_for_text("Grok", session_connected=True, offline=False) is False
    assert uses_gemini_live_for_text("Gemini", session_connected=True, offline=True) is False


def test_tool_schema_translation_lowercases_gemini_types():
    tools = gemini_declarations_to_openai_tools([
        {
            "name": "weather_report",
            "description": "Live weather",
            "parameters": {
                "type": "OBJECT",
                "properties": {"city": {"type": "STRING", "description": "City"}},
                "required": ["city"],
            },
        }
    ])
    assert tools[0]["type"] == "function"
    function = tools[0]["function"]
    assert function["name"] == "weather_report"
    assert function["parameters"]["type"] == "object"
    assert function["parameters"]["properties"]["city"]["type"] == "string"


def test_default_grok_model_comes_from_the_fetched_list():
    chosen = choose_default_model("grok", ["grok-2-latest", "grok-4-vision", "grok-4", "grok-3"])
    assert chosen == "grok-4"
    assert choose_default_model("grok", []) == ""


def test_grok_chat_posts_openai_tools(monkeypatch):
    captured = {}

    class _Response:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "weather_report",
                                "arguments": "{\"city\":\"Orlando\"}",
                            },
                        }],
                    }
                }]
            }

    def _post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _Response()

    result = chat_completion(
        get_preset("grok"),
        api_key="xai-test",
        model="grok-4",
        messages=[{"role": "user", "content": "weather"}],
        tools=gemini_declarations_to_openai_tools([
            {"name": "weather_report", "description": "weather", "parameters": {"type": "OBJECT", "properties": {}}}
        ]),
        http_post=_post,
    )
    assert captured["url"] == "https://api.x.ai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer xai-test"
    assert captured["json"]["model"] == "grok-4"
    assert captured["json"]["tools"][0]["function"]["name"] == "weather_report"
    assert result["tool_calls"][0]["arguments"] == {"city": "Orlando"}


def test_grok_failure_is_a_provider_error_with_notice():
    class _Response:
        status_code = 401
        text = "bad key"

        def json(self):
            return {}

    with pytest.raises(ProviderCallError) as caught:
        chat_completion(
            get_preset("grok"),
            api_key="nope",
            model="grok-4",
            messages=[{"role": "user", "content": "hi"}],
            http_post=lambda *a, **k: _Response(),
        )
    assert caught.value.status == 401
    assert grok_failure_notice() == "SYS: Grok request failed; using Gemini for this reply."


def test_chat_provider_setting_selects_grok_and_skips_it_offline(monkeypatch):
    monkeypatch.setattr(llm_providers.config_manager, "load_settings", lambda: {
        "chat_ai_provider": "grok",
        "default_ai_provider": "Gemini",
        "offline_mode_enabled": False,
    })
    assert llm_providers.selected_chat_preset().id == "grok"
    assert llm_providers.active_text_preset().id == "grok"
    assert provider_id_from_setting("Ollama (experimental)") == "ollama"
    assert provider_id_from_setting("llama.cpp server (experimental)") == "llamacpp"

    monkeypatch.setattr(llm_providers.config_manager, "load_settings", lambda: {
        "chat_ai_provider": "grok",
        "offline_mode_enabled": True,
    })
    assert llm_providers.active_text_preset() is None


def test_grok_http_failure_asks_caller_to_use_gemini(monkeypatch):
    monkeypatch.setattr(llm_providers.config_manager, "load_settings", lambda: {
        "chat_ai_provider": "grok",
        "default_ai_provider": "Grok",
        "chat_ai_model": "grok-4",
    })
    monkeypatch.setattr(llm_providers, "load_api_key", lambda preset: "bad-key")

    class _Response:
        status_code = 429
        text = "slow down"

        def json(self):
            return {}

    monkeypatch.setattr(llm_providers.requests, "post", lambda *a, **k: _Response())
    text, notice = llm_providers.try_provider_text("You are Brahma.", "Hello")
    assert text is None
    assert notice == grok_failure_notice()


def test_model_list_reads_openai_data(monkeypatch):
    class _Response:
        status_code = 200

        def json(self):
            return {"data": [{"id": "grok-3"}, {"id": "grok-4"}]}

    names = llm_providers.list_models(
        get_preset("grok"),
        "xai-test",
        http_get=lambda *a, **k: _Response(),
    )
    assert names == ["grok-3", "grok-4"]
    assert json.dumps(names)
