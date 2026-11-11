"""Short response-style presets for text-chat providers.

Gemini Live keeps its own realtime voice persona. These presets are prepended
to text-chat system prompts only. Missing settings mean "none", so an existing
install keeps today's prompt until someone picks a style.

Ollama and llama.cpp default to Direct / Rigor when the user has not chosen
a style yet. ``PROVIDER_STYLE_DEFAULTS`` is the hook for that.
"""

from __future__ import annotations

import re

from memory import config_manager


STYLE_SETTING = "response_style"
STYLE_CUSTOM_SETTING = "response_style_custom"

# Built-in default used only when the user has not saved a global style or a
# per-provider override. Add future local runtimes here.
PROVIDER_STYLE_DEFAULTS = {
    "ollama": "rigor",
    "llamacpp": "rigor",
}

STYLE_NONE = "none"
STYLE_RIGOR = "rigor"
STYLE_WARM = "warm"
STYLE_CUSTOM = "custom"

STYLE_LABELS = {
    STYLE_NONE: "None / Default",
    STYLE_RIGOR: "Direct / Rigor",
    STYLE_WARM: "Warm / Chat",
    STYLE_CUSTOM: "Custom",
}

# Short labeled chunks. Keep each built-in preset under about 150 words.
# Do not tell the model to state an assumption and proceed; that makes small
# models guess.
RIGOR_TEXT = """\
Identity: You are Brahma Evo, a desktop assistant. Do the task. Do not flatter.

Answer: Lead with the answer, then the reasoning. Match depth to the question. A quick question gets a short reply.

Honesty: Be honest rather than agreeable. If the plan has a flaw, say so and give a better route. If you are not sure, say "I'm not sure." Never invent facts, numbers, or sources. If something is unclear, ask one brief question or say what you do not know.

Thinking: On hard problems, think step by step before the answer.

Shape: Plain prose. Use a list only for a real list. No filler openers. No closing offers.

Code: Working code first. A brief explanation after. Flag real risks only.

Tools: When a tool can do the action, call it. Do not claim you lack access.
"""

WARM_TEXT = """\
Identity: You are Brahma Evo, a knowledgeable, frank friend. Warm, but no praise and no flattery.

Answer: Answer first. Add only the context that helps. A quick question gets a quick reply.

Opinion: When asked what you think, give a real opinion. Do not answer with only "it depends."

Shape: Casual conversation. No lists. No headers. No filler openers. No closing offers.

Tools: If the user wants something done on the computer, call the tool, then say what you did in one sentence.
"""

PRESET_TEXT = {
    STYLE_NONE: "",
    STYLE_RIGOR: RIGOR_TEXT.strip(),
    STYLE_WARM: WARM_TEXT.strip(),
}


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def normalize_style_id(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {STYLE_RIGOR, "direct", "direct / rigor", "direct/rigor"}:
        return STYLE_RIGOR
    if raw in {STYLE_WARM, "chat", "warm / chat", "warm/chat"}:
        return STYLE_WARM
    if raw in {STYLE_CUSTOM, "custom prompt"}:
        return STYLE_CUSTOM
    if raw in {STYLE_NONE, "default", "none / default", "none/default"}:
        return STYLE_NONE
    return STYLE_NONE


def _override_key(provider_id: str) -> str:
    return f"response_style_{provider_id}"


def _custom_key(provider_id: str | None) -> str:
    if provider_id:
        return f"response_style_custom_{provider_id}"
    return STYLE_CUSTOM_SETTING


def resolved_style_id(provider_id: str | None = None) -> str:
    """Style id after override, then global choice, then provider default."""
    settings = config_manager.load_settings()
    if provider_id:
        override = str(settings.get(_override_key(provider_id)) or "").strip()
        if override:
            return normalize_style_id(override)
    global_style = str(settings.get(STYLE_SETTING) or "").strip()
    if global_style:
        return normalize_style_id(global_style)
    if provider_id and provider_id in PROVIDER_STYLE_DEFAULTS:
        return PROVIDER_STYLE_DEFAULTS[provider_id]
    return STYLE_NONE


def style_text(provider_id: str | None = None) -> str:
    """The chunk to prepend. Empty means leave the existing prompt untouched."""
    style_id = resolved_style_id(provider_id)
    if style_id == STYLE_NONE:
        return ""
    if style_id == STYLE_CUSTOM:
        settings = config_manager.load_settings()
        if provider_id and normalize_style_id(str(settings.get(_override_key(provider_id)) or "")) == STYLE_CUSTOM:
            specific = str(settings.get(_custom_key(provider_id)) or "").strip()
            if specific:
                return specific
        return str(settings.get(STYLE_CUSTOM_SETTING) or "").strip()
    return PRESET_TEXT.get(style_id, "")


def compose_system_prompt(base: str, *, provider_id: str | None = None) -> str:
    """Prepend the selected style. None / Default returns ``base`` unchanged."""
    block = style_text(provider_id)
    base = base or ""
    if not block:
        return base
    if base.startswith(block):
        return base
    if not base.strip():
        return block
    return f"{block}\n\n{base.strip()}"


def apply_style_to_messages(messages: list[dict], provider_id: str | None) -> list[dict]:
    """Return messages with the style on the first system turn.

    When no style applies, the original list is returned unchanged.
    """
    block = style_text(provider_id)
    if not block:
        return messages
    copied = [dict(message) for message in messages]
    for message in copied:
        if message.get("role") == "system":
            content = str(message.get("content") or "")
            if content.startswith(block):
                return copied
            message["content"] = f"{block}\n\n{content.strip()}" if content.strip() else block
            return copied
    return [{"role": "system", "content": block}, *copied]


def describe_resolved_style(provider_id: str | None, provider_label: str = "") -> str:
    style_id = resolved_style_id(provider_id)
    label = STYLE_LABELS.get(style_id, STYLE_LABELS[STYLE_NONE])
    who = provider_label or (provider_id or "This chat")
    settings = config_manager.load_settings()
    override = str(settings.get(_override_key(provider_id)) or "").strip() if provider_id else ""
    global_style = str(settings.get(STYLE_SETTING) or "").strip()
    if not override and not global_style and provider_id in PROVIDER_STYLE_DEFAULTS and style_id == PROVIDER_STYLE_DEFAULTS[provider_id]:
        return f"{who} will use {label}. That is the built-in default for this local provider until you choose a style."
    return f"{who} will use {label}."
