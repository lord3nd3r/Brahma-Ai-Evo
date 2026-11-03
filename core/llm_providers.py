"""OpenAI-compatible chat providers.

Gemini stays the default and the only realtime voice engine. OpenRouter and
Grok (xAI) speak the same chat/completions protocol. Ollama and llama.cpp are
experimental presets with the same shape and no API key, so a later local
runtime can drop in without a new client.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

import requests

from memory import config_manager


class ProviderCallError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    base_url: str
    key_field: str
    requires_key: bool
    experimental: bool = False
    fallback_model: str = ""


PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        id="gemini",
        label="Gemini",
        base_url="",
        key_field="gemini_api_key",
        requires_key=True,
        fallback_model="gemini-2.5-flash",
    ),
    ProviderPreset(
        id="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_field="openrouter_api_key",
        requires_key=True,
        fallback_model="openrouter/auto",
    ),
    ProviderPreset(
        id="grok",
        label="Grok (xAI)",
        base_url="https://api.x.ai/v1",
        key_field="xai_api_key",
        requires_key=True,
    ),
    # Experimental local presets. Not the default, and they do not replace Gemini Live.
    ProviderPreset(
        id="ollama",
        label="Ollama (experimental)",
        base_url="http://localhost:11434/v1",
        key_field="",
        requires_key=False,
        experimental=True,
    ),
    ProviderPreset(
        id="llamacpp",
        label="llama.cpp server (experimental)",
        base_url="http://localhost:8080/v1",
        key_field="",
        requires_key=False,
        experimental=True,
    ),
)

_BY_ID = {preset.id: preset for preset in PRESETS}

CHAT_PROVIDER_SETTING = "chat_ai_provider"
CHAT_MODEL_SETTING = "chat_ai_model"


def get_preset(provider_id: str | None) -> ProviderPreset:
    return _BY_ID.get((provider_id or "").strip().lower(), _BY_ID["gemini"])


def visible_presets(*, include_experimental: bool = True) -> list[ProviderPreset]:
    if include_experimental:
        return list(PRESETS)
    return [preset for preset in PRESETS if not preset.experimental]


def provider_id_from_setting(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {"grok", "xai", "x.ai", "grok (xai)"} or raw.startswith("grok"):
        return "grok"
    if "openrouter" in raw:
        return "openrouter"
    if "ollama" in raw:
        return "ollama"
    if "llama" in raw:
        return "llamacpp"
    if raw in {"local"}:
        return "gemini"
    return "gemini"


def selected_chat_preset() -> ProviderPreset:
    settings = config_manager.load_settings()
    explicit = settings.get(CHAT_PROVIDER_SETTING)
    if explicit:
        return get_preset(provider_id_from_setting(str(explicit)))
    return get_preset(provider_id_from_setting(str(settings.get("default_ai_provider") or "gemini")))


def uses_gemini_live_for_text(provider_id: str, *, session_connected: bool, offline: bool) -> bool:
    """Realtime voice stays on Gemini Live. Only a Gemini text selection rides that session."""
    if offline or not session_connected:
        return False
    return get_preset(provider_id_from_setting(provider_id)).id == "gemini"


def is_openai_compatible(preset: ProviderPreset) -> bool:
    return bool(preset.base_url)


def _lowercase_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    converted: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            converted[key] = value.lower()
        elif isinstance(value, dict):
            converted[key] = _lowercase_schema(value)
        elif isinstance(value, list):
            converted[key] = [
                _lowercase_schema(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            converted[key] = value
    return converted


def gemini_declarations_to_openai_tools(declarations: list[dict] | None) -> list[dict]:
    """Translate the app's Gemini tool declarations into OpenAI chat tools."""
    tools: list[dict] = []
    for decl in declarations or []:
        if not isinstance(decl, dict) or not decl.get("name"):
            continue
        parameters = decl.get("parameters") or {"type": "object", "properties": {}}
        tools.append({
            "type": "function",
            "function": {
                "name": decl["name"],
                "description": decl.get("description") or "",
                "parameters": _lowercase_schema(parameters),
            },
        })
    return tools


def choose_default_model(provider_id: str, models: list[str]) -> str:
    """Pick a sensible default from a live model list. Never invents a Grok id."""
    cleaned = [model.strip() for model in models if model and str(model).strip()]
    if not cleaned:
        return get_preset(provider_id).fallback_model
    if provider_id == "openrouter" and "openrouter/auto" in cleaned:
        return "openrouter/auto"
    if provider_id != "grok":
        return cleaned[0]

    def rank(name: str) -> tuple:
        low = name.lower()
        penalty = 50 if any(token in low for token in ("image", "vision", "tts", "embed")) else 0
        major = 9
        for index, token in enumerate(("grok-4", "grok-3", "grok-2", "grok")):
            if token in low:
                major = index
                break
        return (penalty, major, len(low), low)

    return sorted(cleaned, key=rank)[0]


def list_models(preset: ProviderPreset, api_key: str = "", *, http_get: Callable | None = None) -> list[str]:
    if preset.id == "gemini":
        return ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
    if not preset.base_url:
        return []
    getter = http_get or requests.get
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = getter(f"{preset.base_url.rstrip('/')}/models", headers=headers, timeout=8)
    status = getattr(response, "status_code", 200)
    if status >= 400:
        raise ProviderCallError(f"{preset.label} model list failed (HTTP {status}).", status=status)
    payload = response.json() if hasattr(response, "json") else {}
    rows = payload.get("data") or payload.get("models") or []
    names: list[str] = []
    for row in rows:
        if isinstance(row, str):
            names.append(row)
            continue
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or row.get("name") or "").strip()
        if model_id:
            names.append(model_id)
    return names


def chat_completion(
    preset: ProviderPreset,
    *,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.4,
    timeout: float = 30,
    http_post: Callable | None = None,
) -> dict:
    """One OpenAI-compatible chat/completions call."""
    if not preset.base_url:
        raise ProviderCallError(f"{preset.label} is not an OpenAI-compatible endpoint.")
    if preset.requires_key and not (api_key or "").strip():
        raise ProviderCallError(f"{preset.label} API key is missing.")
    if not model:
        raise ProviderCallError(f"No model selected for {preset.label}.")

    poster = http_post or requests.post
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if preset.id == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/brahma-ai"
        headers["X-Title"] = "Brahma Evo"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    response = poster(
        f"{preset.base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    status = getattr(response, "status_code", 200)
    if status in (401, 403):
        raise ProviderCallError(f"{preset.label} rejected the API key (HTTP {status}).", status=status)
    if status == 429:
        raise ProviderCallError(f"{preset.label} rate limit (HTTP 429).", status=status)
    if status >= 400:
        detail = ""
        try:
            detail = response.text[:180]
        except Exception:
            detail = ""
        raise ProviderCallError(f"{preset.label} request failed (HTTP {status}). {detail}".strip(), status=status)

    data = response.json()
    message = ((data.get("choices") or [{}])[0].get("message") or {})
    tool_calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        raw_args = function.get("arguments") or {}
        if isinstance(raw_args, str):
            try:
                arguments = json.loads(raw_args) if raw_args.strip() else {}
            except json.JSONDecodeError:
                arguments = {}
        elif isinstance(raw_args, dict):
            arguments = raw_args
        else:
            arguments = {}
        tool_calls.append({
            "id": call.get("id") or "",
            "name": function.get("name") or "",
            "arguments": arguments,
        })
    content = message.get("content") or ""
    return {
        "content": content.strip() if isinstance(content, str) else str(content or ""),
        "tool_calls": tool_calls,
        "message": message,
    }


def run_tool_conversation(
    preset: ProviderPreset,
    *,
    api_key: str,
    model: str,
    messages: list[dict],
    gemini_tools: list[dict] | None,
    execute_tool: Callable[[str, dict], str],
    max_rounds: int = 3,
    http_post: Callable | None = None,
) -> str:
    """Chat, run any tool calls, then ask the model for the user-facing reply."""
    openai_tools = gemini_declarations_to_openai_tools(gemini_tools)
    transcript = list(messages)
    final = ""
    for _round in range(max_rounds):
        result = chat_completion(
            preset,
            api_key=api_key,
            model=model,
            messages=transcript,
            tools=openai_tools or None,
            http_post=http_post,
        )
        final = result["content"]
        calls = [call for call in result["tool_calls"] if call.get("name")]
        if not calls:
            return final
        transcript.append(result["message"] or {
            "role": "assistant",
            "content": final,
            "tool_calls": result["tool_calls"],
        })
        for call in calls:
            output = execute_tool(call["name"], call["arguments"])
            transcript.append({
                "role": "tool",
                "tool_call_id": call["id"] or call["name"],
                "name": call["name"],
                "content": str(output),
            })
    return final or "Done."


def load_api_key(preset: ProviderPreset) -> str:
    if not preset.key_field:
        return ""
    from core.user_paths import get_user_config_dir
    path = get_user_config_dir() / "api_keys.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    return str(data.get(preset.key_field) or "").strip()


def saved_chat_model() -> str:
    return str(config_manager.get_setting(CHAT_MODEL_SETTING, "") or "").strip()


def complete_text(
    preset: ProviderPreset,
    *,
    system: str,
    user: str,
    model: str | None = None,
    http_get: Callable | None = None,
    http_post: Callable | None = None,
) -> str:
    api_key = load_api_key(preset)
    chosen = (model or saved_chat_model() or "").strip()
    if not chosen:
        models = list_models(preset, api_key, http_get=http_get)
        chosen = choose_default_model(preset.id, models)
    result = chat_completion(
        preset,
        api_key=api_key,
        model=chosen,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        http_post=http_post,
    )
    return result["content"]


def grok_failure_notice() -> str:
    return "SYS: Grok request failed; using Gemini for this reply."


def reply_with_tools(
    preset: ProviderPreset,
    *,
    system: str,
    user: str,
    gemini_tools: list[dict] | None,
    execute_tool: Callable[[str, dict], str],
    model: str | None = None,
    http_get: Callable | None = None,
    http_post: Callable | None = None,
) -> str:
    """One tool-capable chat turn against the preset's OpenAI-compatible endpoint."""
    api_key = load_api_key(preset)
    chosen = (model or saved_chat_model() or "").strip()
    if not chosen:
        chosen = choose_default_model(preset.id, list_models(preset, api_key, http_get=http_get))
    return run_tool_conversation(
        preset,
        api_key=api_key,
        model=chosen,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        gemini_tools=gemini_tools,
        execute_tool=execute_tool,
        http_post=http_post,
    )


def active_text_preset() -> ProviderPreset | None:
    """OpenAI-compatible preset that should replace Gemini for text turns.

    Gemini Live, the existing OpenRouter client, and Local/offline mode stay
    on their own paths. Grok, Ollama, and llama.cpp use this layer.
    """
    settings = config_manager.load_settings()
    if settings.get("offline_mode_enabled"):
        return None
    if str(settings.get("default_ai_provider") or "").strip().lower() == "local":
        return None
    preset = selected_chat_preset()
    if preset.id in {"grok", "ollama", "llamacpp"} and preset.base_url:
        return preset
    return None


def try_provider_messages(messages: list[dict]) -> tuple[str | None, str]:
    """Send a text turn to the selected provider.

    Returns ``(text, "")`` on success. Returns ``(None, notice)`` when the
    call fails and the caller should use Gemini. Returns ``(None, "")`` when
    no OpenAI-compatible chat provider is selected.
    """
    preset = active_text_preset()
    if preset is None:
        return None, ""
    try:
        api_key = load_api_key(preset)
        model = saved_chat_model()
        if not model:
            model = choose_default_model(preset.id, list_models(preset, api_key))
        result = chat_completion(
            preset,
            api_key=api_key,
            model=model,
            messages=messages,
        )
        text = (result.get("content") or "").strip()
        if not text and not result.get("tool_calls"):
            raise ProviderCallError(f"{preset.label} returned an empty reply.")
        return text, ""
    except Exception as exc:
        notice = (
            grok_failure_notice()
            if preset.id == "grok"
            else f"SYS: {preset.label} request failed; using Gemini for this reply."
        )
        print(f"[LLM] {notice} ({exc})")
        return None, notice


def try_provider_text(system: str, user: str) -> tuple[str | None, str]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return try_provider_messages(messages)
