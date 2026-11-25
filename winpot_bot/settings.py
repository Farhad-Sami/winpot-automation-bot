"""Per-user persistent runtime settings for the Telegram browser bot."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from winpot_bot.paths import app_dir

USER_SETTINGS_DIR = app_dir() / "user_settings"
DEFAULT_WINPOT_URL = "https://www.winpot.mx/sport"
CONCURRENCY_OPTIONS = (3, 5, 10)


@dataclass(slots=True)
class BotSettings:
    """Per-user runtime settings configurable via Telegram /settings."""

    headless: bool = True
    summary_mode: str = "analysis"  # "analysis" or "text"
    use_vision: bool = False
    confirm_before_bet: bool = True
    max_concurrency: int = 5
    default_url: str = DEFAULT_WINPOT_URL
    system_prompt: str = ""
    access_token: str = ""
    openrouter_api_key: str = ""


def _env_headless_default() -> bool:
    return os.getenv("HEADLESS", "true").strip().lower() not in {"0", "false", "no"}


def _resolve_path(user_id: int | str = "default", path: Path | None = None) -> Path:
    if path is not None:
        return path
    return USER_SETTINGS_DIR / f"{user_id}.json"


def load_settings(user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Load settings for `user_id` from disk, falling back to defaults."""
    target = _resolve_path(user_id, path)
    defaults = BotSettings(headless=_env_headless_default())
    if not target.exists():
        return defaults
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        mode = str(data.get("summary_mode", defaults.summary_mode)).strip().lower()
        if mode not in {"analysis", "text"}:
            mode = "analysis"
        max_conc = int(data.get("max_concurrency", defaults.max_concurrency))
        max_conc = max(1, min(20, max_conc))
        default_url = str(data.get("default_url", defaults.default_url)).strip() or DEFAULT_WINPOT_URL
        return BotSettings(
            headless=bool(data.get("headless", defaults.headless)),
            summary_mode=mode,
            use_vision=bool(data.get("use_vision", defaults.use_vision)),
            confirm_before_bet=bool(data.get("confirm_before_bet", defaults.confirm_before_bet)),
            max_concurrency=max_conc,
            default_url=default_url,
            system_prompt=str(data.get("system_prompt", "")).strip(),
            access_token=str(data.get("access_token", "")).strip(),
            openrouter_api_key=str(data.get("openrouter_api_key", "")).strip(),
        )
    except Exception:
        return defaults


def save_settings(
    settings: BotSettings,
    user_id: int | str = "default",
    path: Path | None = None,
) -> BotSettings:
    """Persist settings for `user_id` to disk."""
    target = _resolve_path(user_id, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    return settings


def toggle_headless(user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Flip the headless setting and save."""
    settings = load_settings(user_id, path)
    settings.headless = not settings.headless
    return save_settings(settings, user_id, path)


def toggle_summary_mode(user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Switch between 'analysis' and 'text' summary modes and save."""
    settings = load_settings(user_id, path)
    settings.summary_mode = "text" if settings.summary_mode == "analysis" else "analysis"
    return save_settings(settings, user_id, path)


def toggle_vision(user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Flip sending page screenshots to the decision model and save."""
    settings = load_settings(user_id, path)
    settings.use_vision = not settings.use_vision
    return save_settings(settings, user_id, path)


def toggle_confirm_before_bet(user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Flip requiring Telegram confirmation before placing a bet."""
    settings = load_settings(user_id, path)
    settings.confirm_before_bet = not settings.confirm_before_bet
    return save_settings(settings, user_id, path)


def cycle_max_concurrency(user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Cycle max parallel profiles through 3 -> 5 -> 10."""
    settings = load_settings(user_id, path)
    try:
        idx = CONCURRENCY_OPTIONS.index(settings.max_concurrency)
        settings.max_concurrency = CONCURRENCY_OPTIONS[(idx + 1) % len(CONCURRENCY_OPTIONS)]
    except ValueError:
        settings.max_concurrency = CONCURRENCY_OPTIONS[0]
    return save_settings(settings, user_id, path)


def set_default_url(url: str, user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Update the default target URL and save."""
    settings = load_settings(user_id, path)
    cleaned = url.strip()
    if cleaned and not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    settings.default_url = cleaned or DEFAULT_WINPOT_URL
    return save_settings(settings, user_id, path)


def set_system_prompt(prompt: str, user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Update the persistent custom system prompt and save."""
    settings = load_settings(user_id, path)
    settings.system_prompt = prompt.strip()
    return save_settings(settings, user_id, path)


def set_access_token(token: str, user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Save the user's access token."""
    settings = load_settings(user_id, path)
    settings.access_token = token.strip()
    return save_settings(settings, user_id, path)


def set_openrouter_api_key(api_key: str, user_id: int | str = "default", path: Path | None = None) -> BotSettings:
    """Save the user's OpenRouter API key."""
    settings = load_settings(user_id, path)
    settings.openrouter_api_key = api_key.strip()
    return save_settings(settings, user_id, path)
