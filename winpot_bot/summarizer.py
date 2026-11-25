"""Summarize visited page content using OpenRouter (with plain-text fallback)."""

from __future__ import annotations

import os

from winpot_bot.ai import openrouter_chat
from winpot_bot.browser_manager import PageContent

MAX_INPUT_CHARS = 8000
MAX_TELEGRAM_CHARS = 3800


def _format_header(page: PageContent) -> str:
    """Format the standard profile, title, and URL header."""
    return (
        f"Profile: {page.profile_name}\n"
        f"Title: {page.title or '(no title)'}\n"
        f"URL: {page.final_url}"
    )


def _fallback_format(page: PageContent) -> str:
    """Format extracted page content without calling an LLM."""
    parts = [_format_header(page)]
    if page.meta_description:
        parts.append(f"Description: {page.meta_description}")
    excerpt = page.text[:2500] if page.text else "(no visible text)"
    if len(page.text) > 2500:
        excerpt += "\n..."
    parts.append(f"\nContent:\n{excerpt}")
    return "\n".join(parts)[:MAX_TELEGRAM_CHARS]


def select_model(summary_mode: str = "analysis") -> str:
    """Select the OpenRouter model based on summary mode and .env configuration."""
    if summary_mode == "text":
        return (os.getenv("AI_MODEL_TEXT") or os.getenv("AI_MODEL") or "mistralai/mistral-nemo").strip()
    return (os.getenv("AI_MODEL_ANALYSIS") or os.getenv("AI_MODEL") or "qwen/qwen3.7-flash").strip()


async def summarize_page(
    page: PageContent,
    summary_mode: str = "analysis",
    custom_instructions: str = "",
    api_key: str = "",
) -> str:
    """Summarize `page` with OpenRouter if configured, otherwise return a clean extract."""
    provider = os.getenv("AI_PROVIDER", "openrouter").strip().lower()
    if provider != "openrouter" or not api_key.strip():
        return _fallback_format(page)

    system_prompt = (
        "Summarize this web page in 3-5 short bullet points under 600 characters."
        if summary_mode == "text"
        else (
            "You summarize web pages concisely for a Telegram user. "
            "Describe what the page is about, key sections/offers/events visible, "
            "and any notable details. Keep it under 1200 characters."
        )
    )
    if custom_instructions.strip():
        system_prompt += f"\n\nFollow these standing instructions:\n{custom_instructions.strip()}"

    user_content = (
        f"URL: {page.final_url}\n"
        f"Title: {page.title}\n"
        f"Meta: {page.meta_description}\n\n"
        f"Visible text:\n{page.text[:MAX_INPUT_CHARS]}"
    )
    try:
        summary = await openrouter_chat(
            model=select_model(summary_mode),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            api_key=api_key,
        )
        return f"{_format_header(page)}\n\n{summary}"[:MAX_TELEGRAM_CHARS]
    except Exception:
        return _fallback_format(page)
