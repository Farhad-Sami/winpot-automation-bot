"""Unit tests for profile management, settings, Jev action space, router, and UI helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from jev_ultrafast.model import action_space
from winpot_bot.access import parse_access_response
from winpot_bot.ai import extract_json
from winpot_bot.bot import _main_menu_text, _profiles_keyboard, _settings_text
from winpot_bot.browser_manager import (
    PageContent,
    create_profile,
    delete_profile,
    get_profile_dir,
    list_profiles,
    rename_profile,
    sanitize_profile_name,
    validate_url,
)
from winpot_bot.jev_agent import validate_decision
from winpot_bot.router import parse_route_json
from winpot_bot.settings import (
    BotSettings,
    cycle_max_concurrency,
    load_settings,
    set_default_url,
    set_openrouter_api_key,
    set_system_prompt,
    toggle_confirm_before_bet,
    toggle_headless,
    toggle_summary_mode,
)
from winpot_bot.summarizer import select_model, summarize_page


def test_sanitize_profile_name() -> None:
    assert sanitize_profile_name("winpot_1") == "winpot_1"
    with pytest.raises(ValueError):
        sanitize_profile_name("../escape")
    with pytest.raises(ValueError):
        sanitize_profile_name("bad name")
    with pytest.raises(ValueError):
        sanitize_profile_name("all")


def test_profile_crud(tmp_path: Path) -> None:
    p1 = create_profile("alpha", base_dir=tmp_path)
    assert p1.is_dir()
    with pytest.raises(FileExistsError):
        create_profile("alpha", base_dir=tmp_path)

    get_profile_dir("beta", base_dir=tmp_path)
    assert list_profiles(base_dir=tmp_path) == ["alpha", "beta"]

    renamed = rename_profile("alpha", "gamma", base_dir=tmp_path)
    assert renamed.name == "gamma"
    assert list_profiles(base_dir=tmp_path) == ["beta", "gamma"]

    delete_profile("beta", base_dir=tmp_path)
    assert list_profiles(base_dir=tmp_path) == ["gamma"]

    with pytest.raises(FileNotFoundError):
        delete_profile("missing", base_dir=tmp_path)


def test_settings_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEADLESS", "true")
    settings_file = tmp_path / "settings.json"

    initial = load_settings(settings_file)
    assert initial.headless is True
    assert initial.summary_mode == "analysis"

    after_headless = toggle_headless(settings_file)
    assert after_headless.headless is False

    after_mode = toggle_summary_mode(settings_file)
    assert after_mode.summary_mode == "text"

    with_prompt = set_system_prompt("Always wait 5s and reply in English", settings_file)
    assert with_prompt.system_prompt == "Always wait 5s and reply in English"
    assert load_settings(settings_file).system_prompt == "Always wait 5s and reply in English"

    assert toggle_confirm_before_bet(path=settings_file).confirm_before_bet is False
    assert cycle_max_concurrency(path=settings_file).max_concurrency == 10
    assert set_default_url("winpot.mx/casino", path=settings_file).default_url == "https://winpot.mx/casino"
    assert set_openrouter_api_key("sk-or-test-1234", path=settings_file).openrouter_api_key == "sk-or-test-1234"


def test_per_user_settings_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import winpot_bot.settings as settings_mod

    monkeypatch.setattr(settings_mod, "USER_SETTINGS_DIR", tmp_path)
    set_openrouter_api_key("key-user-1", user_id=111)
    set_openrouter_api_key("key-user-2", user_id=222)
    assert load_settings(111).openrouter_api_key == "key-user-1"
    assert load_settings(222).openrouter_api_key == "key-user-2"


def test_select_model_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_MODEL_ANALYSIS", "qwen/qwen3.7-flash")
    monkeypatch.setenv("AI_MODEL_TEXT", "mistralai/mistral-nemo")
    assert select_model("analysis") == "qwen/qwen3.7-flash"
    assert select_model("text") == "mistralai/mistral-nemo"


@pytest.mark.anyio
async def test_summarize_page_fallback_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    page = PageContent(
        profile_name="winpot",
        requested_url="https://www.winpot.mx/sport",
        final_url="https://www.winpot.mx/sport",
        title="Winpot Sports",
        meta_description="Sports betting",
        text="Live matches and odds",
    )
    result = await summarize_page(page)
    assert "Profile: winpot" in result
    assert "Title: Winpot Sports" in result
    assert "Live matches and odds" in result


def test_ui_menu_helpers() -> None:
    settings = BotSettings(headless=True, summary_mode="analysis")
    menu_text = _main_menu_text(settings, ["winpot", "acc2"])
    assert "AutoWinPotBot Dashboard" in menu_text
    assert "Saved Profiles:</b> 2" in menu_text

    settings_text = _settings_text(settings)
    assert "Headless:</b> ON" in settings_text

    kb = _profiles_keyboard(["winpot", "acc2"], {"winpot"})
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "✅ winpot" in labels
    assert "⬜ acc2" in labels
    assert "🔓 Open Login" in labels
    assert "☑️ Select All" in labels


def test_jev_action_space_and_wait_validation() -> None:
    actions = [
        {"id": "e1", "kind": "click", "node": 10, "role": "button", "label": "Live"},
        {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
    ]
    elements, targets, controls = action_space(actions)
    assert len(elements) == 1
    assert "CLICK" in targets

    wait_dec = validate_decision(
        {"operation": "WAIT", "target": None, "wait_seconds": 7, "reason": "Wait on page"},
        targets,
        controls,
    )
    assert wait_dec["operation"] == "WAIT"
    assert wait_dec["wait_seconds"] == 7

    clamped_wait = validate_decision({"operation": "WAIT", "wait_seconds": 999}, targets, controls)
    assert clamped_wait["wait_seconds"] == 30


def test_router_and_extract_json() -> None:
    assert extract_json('```json\n{"ok": true}\n```') == {"ok": True}

    auto = parse_route_json(
        '{"tool": "automate", "profiles": ["test1"], "url": "https://www.winpot.mx/sport", "goal": "wait 5s"}',
        selected_profiles=[],
        saved_profiles=["test1"],
    )
    assert auto == {
        "tool": "automate",
        "profiles": ["test1"],
        "url": "https://www.winpot.mx/sport",
        "goal": "wait 5s",
    }

    visit_default = parse_route_json(
        '{"tool": "visit", "url": "https://www.winpot.mx/sport"}',
        selected_profiles=["winpot"],
        saved_profiles=["winpot", "acc2"],
    )
    assert visit_default["profiles"] == ["winpot"]


def test_access_token_validation() -> None:
    active = parse_access_response(
        {"token": "test1", "status": "active", "limit": {"ends": 1796001972}},
        now=1796000000,
    )
    assert active.allowed is True

    expired = parse_access_response(
        {"token": "test1", "status": "active", "limit": {"ends": 1796001972}},
        now=1796002000,
    )
    assert expired.allowed is False
    assert "expired" in expired.reason.lower()

    inactive = parse_access_response(
        {"token": "test1", "status": "revoked", "limit": {"ends": 1796001972}},
        now=1796000000,
    )
    assert inactive.allowed is False


def test_validate_url_blocks_ssrf_and_schemes() -> None:
    assert validate_url("winpot.mx/sport") == "https://winpot.mx/sport"
    assert validate_url("https://www.winpot.mx/sport") == "https://www.winpot.mx/sport"
    for bad in [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://localhost:8080",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1",
    ]:
        with pytest.raises(ValueError):
            validate_url(bad)


def test_per_user_profile_isolation(tmp_path: Path) -> None:
    create_profile("acc1", user_id=111, base_dir=tmp_path)
    create_profile("acc2", user_id=222, base_dir=tmp_path)
    assert list_profiles(user_id=111, base_dir=tmp_path) == ["acc1"]
    assert list_profiles(user_id=222, base_dir=tmp_path) == ["acc2"]
