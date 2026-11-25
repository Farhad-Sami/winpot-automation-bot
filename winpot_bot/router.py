"""Natural-language AI tool router for Telegram messages."""

from __future__ import annotations

import json
import os
from typing import Any

from winpot_bot.ai import extract_json, openrouter_chat
from winpot_bot.browser_manager import sanitize_profile_name

VALID_TOOLS = {
    "automate",
    "visit",
    "create_profile",
    "rename_profile",
    "delete_profile",
    "list_profiles",
    "update_settings",
    "reply",
}


def _resolve_profiles(
    raw_profiles: Any,
    selected_profiles: list[str],
    saved_profiles: list[str],
) -> list[str]:
    if isinstance(raw_profiles, str):
        raw_list = [p.strip() for p in raw_profiles.split(",") if p.strip()]
    elif isinstance(raw_profiles, list):
        raw_list = [str(p).strip() for p in raw_profiles if str(p).strip()]
    else:
        raw_list = []

    if any(p.lower() == "all" for p in raw_list):
        return saved_profiles or ["winpot"]
    if raw_list:
        return [sanitize_profile_name(p) for p in raw_list]
    if selected_profiles:
        return selected_profiles
    if saved_profiles:
        return [saved_profiles[0]]
    return ["winpot"]


def parse_route_json(
    raw: str,
    selected_profiles: list[str],
    saved_profiles: list[str],
) -> dict[str, Any]:
    """Parse and validate the router's JSON tool call."""
    data = extract_json(raw)
    tool = str(data.get("tool", "")).strip()
    if tool not in VALID_TOOLS:
        raise ValueError(f"Unsupported tool '{tool}'.")

    if tool == "visit":
        url = str(data.get("url", "")).strip()
        if not url:
            raise ValueError("Missing URL for visit.")
        return {
            "tool": "visit",
            "profiles": _resolve_profiles(data.get("profiles"), selected_profiles, saved_profiles),
            "url": url,
        }

    if tool == "automate":
        url = str(data.get("url", "")).strip()
        goal = str(data.get("goal", "")).strip()
        if not url or not goal:
            raise ValueError("Missing URL or goal for automate.")
        return {
            "tool": "automate",
            "profiles": _resolve_profiles(data.get("profiles"), selected_profiles, saved_profiles),
            "url": url,
            "goal": goal,
        }

    if tool in {"create_profile", "delete_profile"}:
        return {"tool": tool, "name": sanitize_profile_name(str(data.get("name", "")))}

    if tool == "rename_profile":
        return {
            "tool": "rename_profile",
            "old_name": sanitize_profile_name(str(data.get("old_name", ""))),
            "new_name": sanitize_profile_name(str(data.get("new_name", ""))),
        }

    if tool == "update_settings":
        out: dict[str, Any] = {"tool": "update_settings"}
        for key in ("headless", "use_vision"):
            if data.get(key) is not None:
                out[key] = bool(data[key])
        if data.get("summary_mode") in {"analysis", "text"}:
            out["summary_mode"] = data["summary_mode"]
        return out

    if tool == "list_profiles":
        return {"tool": "list_profiles"}

    return {"tool": "reply", "message": str(data.get("message", "How can I help?")).strip()}


async def route_message(
    user_text: str,
    selected_profiles: list[str],
    saved_profiles: list[str],
    api_key: str = "",
    custom_instructions: str = "",
    default_url: str = "https://www.winpot.mx/sport",
) -> dict[str, Any]:
    """Route any natural-language user message to a structured tool call via OpenRouter."""
    if not api_key.strip():
        return {
            "tool": "reply",
            "message": "🔑 Please set your OpenRouter API key first in /settings or with `/openrouter_key <key>`.",
        }

    model = (os.getenv("AI_MODEL_TEXT") or os.getenv("AI_MODEL") or "mistralai/mistral-nemo").strip()
    system_prompt = (
        "You are the command router for a Telegram browser automation bot. "
        "Convert the user's message into ONE JSON tool call. Return ONLY valid JSON.\n\n"
        "Available tools:\n"
        '1. {"tool": "automate", "profiles": ["..."], "url": "https://...", "goal": "..."}\n'
        "   Use when the user wants to visit a URL AND do something (wait, click, type, extract specific info).\n"
        '2. {"tool": "visit", "profiles": ["..."], "url": "https://..."}\n'
        "   Use when the user only wants to open/visit a URL and get a general summary.\n"
        '3. {"tool": "create_profile", "name": "..."}\n'
        '4. {"tool": "rename_profile", "old_name": "...", "new_name": "..."}\n'
        '5. {"tool": "delete_profile", "name": "..."}\n'
        '6. {"tool": "list_profiles"}\n'
        '7. {"tool": "update_settings", "headless": true|false, '
        '"summary_mode": "analysis"|"text", "use_vision": true|false}\n'
        '8. {"tool": "reply", "message": "..."}\n\n'
        "Rules:\n"
        "- If the user omits profile names, omit 'profiles' or pass [] so selected/default profiles are used.\n"
        "- If the user says 'all profiles', pass [\"all\"].\n"
        f"- If the user omits a URL, use '{default_url}'.\n"
        "- Ensure URLs include https:// if missing."
    )
    if custom_instructions.strip():
        system_prompt += f"\n\nUser's standing instructions:\n{custom_instructions.strip()}"

    user_payload = json.dumps(
        {
            "message": user_text,
            "saved_profiles": saved_profiles,
            "selected_profiles": selected_profiles,
        },
        ensure_ascii=False,
    )
    raw = await openrouter_chat(
        model=model,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_payload}],
        api_key=api_key,
        timeout=20.0,
    )
    return parse_route_json(raw, selected_profiles=selected_profiles, saved_profiles=saved_profiles)
