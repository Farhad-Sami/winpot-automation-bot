"""Telegram bot that visits URLs and runs Jev automations with persistent profiles."""

from __future__ import annotations

import html
import logging
import os

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from winpot_bot.access import verify_access_token
from winpot_bot.browser_manager import (
    PageContent,
    create_profile,
    delete_profile,
    ensure_chromium_installed,
    list_profiles,
    open_profile_for_login,
    rename_profile,
    visit_with_profiles,
)
from winpot_bot.jev_agent import AutomationResult, run_automations
from winpot_bot.paths import app_dir, bundle_dir
from winpot_bot.router import route_message
from winpot_bot.settings import (
    BotSettings,
    cycle_max_concurrency,
    load_settings,
    save_settings,
    set_access_token,
    set_default_url,
    set_openrouter_api_key,
    set_system_prompt,
    toggle_confirm_before_bet,
    toggle_headless,
    toggle_summary_mode,
    toggle_vision,
)
from winpot_bot.summarizer import select_model, summarize_page

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BTN_PROFILES = "👤 Profiles"
BTN_QUICK_WINPOT = "🚀 Quick Winpot"
BTN_SETTINGS = "⚙️ Settings"
BTN_HELP = "❓ Help"

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [
        [BTN_PROFILES, BTN_QUICK_WINPOT],
        [BTN_SETTINGS, BTN_HELP],
    ],
    resize_keyboard=True,
)


def load_env() -> None:
    """Load environment variables from app_dir/bundle_dir (.env and config.env)."""
    for base in (app_dir(), bundle_dir()):
        for name in (".env", "config.env"):
            candidate = base / name
            if candidate.exists():
                load_dotenv(candidate, override=False)


def _uid(update: Update) -> int | str:
    """Return the Telegram user ID for per-user settings isolation."""
    return update.effective_user.id if update.effective_user else "default"


def _mask_secret(value: str) -> str:
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


async def _delete_secret_message(update: Update) -> None:
    """Best-effort removal of secret-bearing messages from chat history."""
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass


async def _require_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verify the user's access token against ACCESS_URL before handling any request."""
    settings = load_settings(_uid(update))
    msg = update.effective_message
    if not settings.access_token:
        context.user_data["awaiting"] = "access_token"
        if msg:
            await msg.reply_text("🔑 Please send your access token to continue (or `/token <token>`):")
        return False

    status = await verify_access_token(settings.access_token)
    if not status.allowed:
        if msg:
            await msg.reply_text(
                f"🔒 Access denied: {status.reason}\n\nSend a new token with /token <token>."
            )
        return False
    return True


def _main_menu_text(settings: BotSettings, profiles: list[str]) -> str:
    model = html.escape(select_model(settings.summary_mode))
    headless_str = "ON (hidden)" if settings.headless else "OFF (visible)"
    return (
        "<b>🤖 AutoWinPotBot Dashboard</b>\n\n"
        f"👤 <b>Saved Profiles:</b> {len(profiles)}\n"
        f"🖥 <b>Headless:</b> {headless_str}\n"
        f"🛡️ <b>Confirm Bet:</b> {'ON' if settings.confirm_before_bet else 'OFF'}\n"
        f"⚡ <b>Max Parallel:</b> {settings.max_concurrency}\n"
        f"🧠 <b>AI Mode:</b> {html.escape(settings.summary_mode)} (<code>{model}</code>)\n\n"
        "<i>Send any natural-language request or tap a button below.</i>"
    )


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 Quick Visit Winpot", callback_data="quick_winpot")],
            [
                InlineKeyboardButton("👤 Manage Profiles", callback_data="menu_profiles"),
                InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
            ],
        ]
    )


def _profiles_text(profiles: list[str], selected: set[str]) -> str:
    if not profiles:
        return (
            "<b>👤 Browser Profiles</b>\n\n"
            "No profiles saved yet. Tap <b>➕ Create Profile</b> to add one."
        )
    sel_count = len(selected & set(profiles))
    return (
        f"<b>👤 Browser Profiles ({len(profiles)})</b>\n"
        f"Selected for next run: <b>{sel_count}</b>\n\n"
        "<i>Tap profiles to select/deselect, then run an action or send any prompt:</i>"
    )


def _profiles_keyboard(profiles: list[str], selected: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(profiles), 2):
        row = []
        for name in profiles[i : i + 2]:
            prefix = "✅" if name in selected else "⬜"
            row.append(InlineKeyboardButton(f"{prefix} {name}", callback_data=f"toggle_prof:{name}"))
        rows.append(row)

    if profiles:
        rows.append(
            [
                InlineKeyboardButton("☑️ Select All", callback_data="select_all_profiles"),
                InlineKeyboardButton("🔓 Open Login", callback_data="login_selected"),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton("🚀 Visit Default", callback_data="visit_winpot_selected"),
                InlineKeyboardButton("➕ Create Profile", callback_data="prompt_create_profile"),
            ]
        )
        rows.append([InlineKeyboardButton("🗑️ Delete Selected", callback_data="delete_selected")])
    else:
        rows.append([InlineKeyboardButton("➕ Create Profile", callback_data="prompt_create_profile")])

    rows.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


def _settings_text(settings: BotSettings) -> str:
    model = html.escape(select_model(settings.summary_mode))
    prompt_preview = html.escape(settings.system_prompt[:100]) if settings.system_prompt else "(none)"
    if len(settings.system_prompt) > 100:
        prompt_preview += "..."
    return (
        "<b>⚙️ Bot Settings</b>\n\n"
        f"🖥 <b>Headless:</b> {'ON (hidden)' if settings.headless else 'OFF (visible)'}\n"
        f"🧠 <b>AI Mode:</b> {html.escape(settings.summary_mode)} (<code>{model}</code>)\n"
        f"👁️ <b>Vision (Screenshots):</b> {'ON' if settings.use_vision else 'OFF'}\n"
        f"🛡️ <b>Confirm Bet:</b> {'ON (safe)' if settings.confirm_before_bet else 'OFF (auto)'}\n"
        f"⚡ <b>Max Parallel:</b> {settings.max_concurrency} profiles\n"
        f"🌐 <b>Default URL:</b> <code>{html.escape(settings.default_url)}</code>\n"
        f"🔑 <b>Access Token:</b> <code>{html.escape(_mask_secret(settings.access_token))}</code>\n"
        f"🗝️ <b>OpenRouter Key:</b> <code>{html.escape(_mask_secret(settings.openrouter_api_key))}</code>\n"
        f"📝 <b>System Prompt:</b> <code>{prompt_preview}</code>"
    )


def _settings_keyboard(settings: BotSettings) -> InlineKeyboardMarkup:
    prompt_row = [InlineKeyboardButton("📝 Set System Prompt", callback_data="prompt_set_system_prompt")]
    if settings.system_prompt:
        prompt_row.append(InlineKeyboardButton("🗑️ Clear Prompt", callback_data="clear_system_prompt"))
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"🖥 Headless: {'ON' if settings.headless else 'OFF'}",
                    callback_data="toggle_headless",
                ),
                InlineKeyboardButton(
                    f"🧠 AI: {settings.summary_mode.title()}",
                    callback_data="toggle_summary_mode",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"👁️ Vision: {'ON' if settings.use_vision else 'OFF'}",
                    callback_data="toggle_vision",
                ),
                InlineKeyboardButton(
                    f"🛡️ Confirm: {'ON' if settings.confirm_before_bet else 'OFF'}",
                    callback_data="toggle_confirm_bet",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"⚡ Parallel: {settings.max_concurrency}",
                    callback_data="cycle_concurrency",
                ),
                InlineKeyboardButton("🌐 Default URL", callback_data="prompt_set_default_url"),
            ],
            [
                InlineKeyboardButton("🔑 Access Token", callback_data="prompt_set_access_token"),
                InlineKeyboardButton("🗝️ OpenRouter Key", callback_data="prompt_set_openrouter_key"),
            ],
            prompt_row,
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu_main")],
        ]
    )


def _get_selected_profiles(context: ContextTypes.DEFAULT_TYPE) -> set[str]:
    selected = context.user_data.setdefault("selected_profiles", set())
    if not isinstance(selected, set):
        selected = set(selected)
        context.user_data["selected_profiles"] = selected
    return selected


def _format_multi_automation_report(
    results: list[AutomationResult | tuple[str, Exception]],
    url: str,
    goal: str,
    dry_run: bool,
) -> str:
    """Format a compact multi-profile report card."""
    title = "🛡️ Betslip Prepared (Confirm to Place)" if dry_run else "🤖 Multi-Profile Automation Report"
    lines = [f"<b>{html.escape(title)}</b>", f"🎯 <b>Goal:</b> {html.escape(goal[:160])}", ""]
    for item in results:
        if isinstance(item, AutomationResult):
            last_step = item.steps[-1] if item.steps else "(no actions)"
            lines.append(
                f"• <b>{html.escape(item.profile_name)}</b> [{item.status.upper()}]: "
                f"{html.escape(last_step[:140])}"
            )
        else:
            failed_name, exc = item
            lines.append(f"• <b>{html.escape(failed_name)}</b> [ERROR]: {html.escape(str(exc)[:140])}")
    return "\n".join(lines)[:3800]


async def _execute_visit(update: Update, profiles: list[str], url: str) -> None:
    """Run `visit_with_profiles` and send formatted results to the chat."""
    chat_message = update.effective_message
    if not chat_message:
        return

    uid = _uid(update)
    settings = load_settings(uid)
    status_msg = await chat_message.reply_text(
        f"⏳ Visiting {url} using profile(s): {', '.join(profiles)}..."
    )
    results = await visit_with_profiles(
        profile_names=profiles,
        url=url,
        headless=settings.headless,
        user_id=uid,
        max_concurrency=settings.max_concurrency,
    )

    for idx, item in enumerate(results):
        if isinstance(item, PageContent):
            text = await summarize_page(
                item,
                summary_mode=settings.summary_mode,
                custom_instructions=settings.system_prompt,
                api_key=settings.openrouter_api_key,
            )
        else:
            failed_name, exc = item
            text = f"Profile: {failed_name}\nError visiting {url}: {exc}"

        if idx == 0:
            await status_msg.edit_text(text)
        else:
            await chat_message.reply_text(text)


async def _execute_automation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    profiles: list[str],
    url: str,
    goal: str,
    confirmed: bool = False,
) -> None:
    """Run multi-step Jev automation across `profiles`, pausing for confirmation if enabled."""
    chat_message = update.effective_message
    if not chat_message:
        return

    uid = _uid(update)
    settings = load_settings(uid)
    dry_run = settings.confirm_before_bet and not confirmed
    status_msg = await chat_message.reply_text(
        f"🤖 {'Preparing' if dry_run else 'Running'} on {url} "
        f"for {len(profiles)} profile(s): {', '.join(profiles)}..."
    )
    results = await run_automations(
        profile_names=profiles,
        url=url,
        goal=goal,
        api_key=settings.openrouter_api_key,
        headless=settings.headless,
        use_vision=settings.use_vision,
        custom_instructions=settings.system_prompt,
        dry_run_before_submit=dry_run,
        user_id=uid,
        max_concurrency=settings.max_concurrency,
    )

    reply_markup = None
    if dry_run:
        context.user_data["pending_automation"] = {
            "profiles": profiles,
            "url": url,
            "goal": goal,
        }
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Confirm & Place", callback_data="confirm_bet_run"),
                    InlineKeyboardButton("❌ Cancel", callback_data="cancel_bet_run"),
                ]
            ]
        )

    if len(results) > 1 or dry_run:
        report = _format_multi_automation_report(results, url=url, goal=goal, dry_run=dry_run)
        await status_msg.edit_text(report, parse_mode="HTML", reply_markup=reply_markup)
        return

    item = results[0]
    if isinstance(item, AutomationResult):
        summary = await summarize_page(
            item.final_page,
            summary_mode=settings.summary_mode,
            custom_instructions=settings.system_prompt,
            api_key=settings.openrouter_api_key,
        )
        steps_block = "\n".join(f"• {s}" for s in item.steps) or "• (no actions taken)"
        text = f"Status: {item.status.upper()}\nSteps:\n{steps_block}\n\n{summary}"[:3800]
    else:
        failed_name, exc = item
        text = f"Profile: {failed_name}\nAutomation error on {url}: {exc}"
    await status_msg.edit_text(text)


async def token_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /token <token> to set and verify the access token."""
    if not update.message:
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /token <your_access_token>")
        return
    token = context.args[0].strip()
    status = await verify_access_token(token)
    if not status.allowed:
        await update.message.reply_text(f"🔒 Token rejected: {status.reason}")
        return
    set_access_token(token, _uid(update))
    context.user_data.pop("awaiting", None)
    await _delete_secret_message(update)
    await update.message.reply_text("✅ Access token verified and saved! Send /start to begin.")


async def openrouter_key_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /openrouter_key <key> to set the user's OpenRouter API key."""
    if not update.message or not await _require_access(update, context):
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /openrouter_key <your_openrouter_api_key>")
        return
    set_openrouter_api_key(context.args[0].strip(), _uid(update))
    context.user_data.pop("awaiting", None)
    await _delete_secret_message(update)
    await update.message.reply_text("✅ OpenRouter API key saved for your account!")


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start."""
    if not update.message:
        return
    if not await _require_access(update, context):
        return
    context.user_data.pop("awaiting", None)
    settings = load_settings(_uid(update))
    profiles = list_profiles(_uid(update))
    await update.message.reply_text(
        _main_menu_text(settings, profiles),
        parse_mode="HTML",
        reply_markup=REPLY_KEYBOARD,
    )
    await update.message.reply_text("Quick Actions:", reply_markup=_main_menu_keyboard())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    if not update.message or not await _require_access(update, context):
        return
    await update.message.reply_text(
        "<b>📖 Commands &amp; Natural Language</b>\n\n"
        "Send any request naturally, for example:\n"
        "• <i>Bet 100 on America vs Chivas, America to win, all profiles</i>\n"
        "• <i>Open winpot.mx/sport with test1, wait 5s, and summarize live football</i>\n\n"
        "/start — Main dashboard\n"
        "/profiles — Manage &amp; select profiles\n"
        "/login &lt;profile&gt; — Open browser window to log in manually\n"
        "/create_profile &lt;name&gt; — Create a profile\n"
        "/rename_profile &lt;old&gt; &lt;new&gt; — Rename a profile\n"
        "/delete_profile &lt;name&gt; — Delete a profile\n"
        "/settings — Customize headless, AI, vision, confirm gate, parallel &amp; prompt",
        parse_mode="HTML",
        reply_markup=REPLY_KEYBOARD,
    )


async def profiles_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /profiles."""
    if not update.message or not await _require_access(update, context):
        return
    profiles = list_profiles(_uid(update))
    selected = _get_selected_profiles(context)
    await update.message.reply_text(
        _profiles_text(profiles, selected),
        parse_mode="HTML",
        reply_markup=_profiles_keyboard(profiles, selected),
    )


async def login_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /login <profile>."""
    if not update.message or not await _require_access(update, context):
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /login <profile_name>")
        return
    name = context.args[0]
    settings = load_settings(_uid(update))
    msg = await update.message.reply_text(
        f"🔓 Opening browser for '{name}'. Log in manually, then close the browser window to save."
    )
    try:
        await open_profile_for_login(name, url=settings.default_url, user_id=_uid(update))
        await msg.edit_text(f"✅ Session saved for profile '{name}'.")
    except Exception as exc:
        await msg.edit_text(f"Error opening login for '{name}': {exc}")


async def create_profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /create_profile <name>."""
    if not update.message or not await _require_access(update, context):
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /create_profile <name>")
        return
    try:
        path = create_profile(context.args[0], user_id=_uid(update))
        await update.message.reply_text(f"✅ Created profile '{path.name}'.")
    except (ValueError, FileExistsError) as exc:
        await update.message.reply_text(str(exc))


async def rename_profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /rename_profile <old> <new>."""
    if not update.message or not await _require_access(update, context):
        return
    if not context.args or len(context.args) != 2:
        await update.message.reply_text("Usage: /rename_profile <old_name> <new_name>")
        return
    try:
        path = rename_profile(context.args[0], context.args[1], user_id=_uid(update))
        await update.message.reply_text(f"✅ Renamed profile to '{path.name}'.")
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        await update.message.reply_text(str(exc))


async def delete_profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete_profile <name>."""
    if not update.message or not await _require_access(update, context):
        return
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("Usage: /delete_profile <name>")
        return
    try:
        delete_profile(context.args[0], user_id=_uid(update))
        await update.message.reply_text(f"🗑️ Deleted profile '{context.args[0]}'.")
    except (ValueError, FileNotFoundError) as exc:
        await update.message.reply_text(str(exc))


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings."""
    if not update.message or not await _require_access(update, context):
        return
    settings = load_settings(_uid(update))
    await update.message.reply_text(
        _settings_text(settings),
        parse_mode="HTML",
        reply_markup=_settings_keyboard(settings),
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all inline keyboard callbacks."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not await _require_access(update, context):
        return

    data = query.data
    uid = _uid(update)
    selected = _get_selected_profiles(context)

    if data == "menu_main":
        settings = load_settings(uid)
        profiles = list_profiles(uid)
        await query.edit_message_text(
            _main_menu_text(settings, profiles),
            parse_mode="HTML",
            reply_markup=_main_menu_keyboard(),
        )
    elif data == "menu_profiles":
        profiles = list_profiles(uid)
        await query.edit_message_text(
            _profiles_text(profiles, selected),
            parse_mode="HTML",
            reply_markup=_profiles_keyboard(profiles, selected),
        )
    elif data == "menu_settings":
        settings = load_settings(uid)
        await query.edit_message_text(
            _settings_text(settings),
            parse_mode="HTML",
            reply_markup=_settings_keyboard(settings),
        )
    elif data in {
        "toggle_headless",
        "toggle_summary_mode",
        "toggle_vision",
        "toggle_confirm_bet",
        "cycle_concurrency",
    }:
        if data == "toggle_headless":
            settings = toggle_headless(uid)
        elif data == "toggle_summary_mode":
            settings = toggle_summary_mode(uid)
        elif data == "toggle_vision":
            settings = toggle_vision(uid)
        elif data == "toggle_confirm_bet":
            settings = toggle_confirm_before_bet(uid)
        else:
            settings = cycle_max_concurrency(uid)
        await query.edit_message_text(
            _settings_text(settings),
            parse_mode="HTML",
            reply_markup=_settings_keyboard(settings),
        )
    elif data == "prompt_set_system_prompt":
        context.user_data["awaiting"] = "system_prompt"
        await query.message.reply_text(
            "Send your standing system prompt/instructions (e.g. 'Default URL is https://www.winpot.mx/sport. "
            "Select the match/market, enter stake, and reply with odds and status'):"
        )
    elif data == "prompt_set_default_url":
        context.user_data["awaiting"] = "default_url"
        await query.message.reply_text("Send the new default URL (e.g. https://www.winpot.mx/sport):")
    elif data == "prompt_set_access_token":
        context.user_data["awaiting"] = "access_token"
        await query.message.reply_text("Send your new access token:")
    elif data == "prompt_set_openrouter_key":
        context.user_data["awaiting"] = "openrouter_api_key"
        await query.message.reply_text("Send your OpenRouter API key (sk-or-...):")
    elif data == "clear_system_prompt":
        settings = set_system_prompt("", uid)
        await query.edit_message_text(
            _settings_text(settings),
            parse_mode="HTML",
            reply_markup=_settings_keyboard(settings),
        )
    elif data.startswith("toggle_prof:"):
        name = data.split(":", 1)[1]
        if name in selected:
            selected.remove(name)
        else:
            selected.add(name)
        profiles = list_profiles(uid)
        await query.edit_message_text(
            _profiles_text(profiles, selected),
            parse_mode="HTML",
            reply_markup=_profiles_keyboard(profiles, selected),
        )
    elif data == "select_all_profiles":
        profiles = list_profiles(uid)
        if set(profiles).issubset(selected):
            selected.clear()
        else:
            selected.update(profiles)
        await query.edit_message_text(
            _profiles_text(profiles, selected),
            parse_mode="HTML",
            reply_markup=_profiles_keyboard(profiles, selected),
        )
    elif data == "login_selected":
        profiles = list_profiles(uid)
        targets = sorted(selected & set(profiles))
        if len(targets) != 1:
            await query.message.reply_text("Select exactly 1 profile to open for manual login.")
            return
        name = targets[0]
        settings = load_settings(uid)
        msg = await query.message.reply_text(
            f"🔓 Opening browser for '{name}'. Log in manually, then close the browser window to save."
        )
        try:
            await open_profile_for_login(name, url=settings.default_url, user_id=uid)
            await msg.edit_text(f"✅ Session saved for profile '{name}'.")
        except Exception as exc:
            await msg.edit_text(f"Error opening login for '{name}': {exc}")
    elif data == "prompt_create_profile":
        context.user_data["awaiting"] = "create_profile"
        await query.message.reply_text("Send the new profile name (letters, numbers, '-' or '_'):")
    elif data == "delete_selected":
        profiles = list_profiles(uid)
        targets = sorted(selected & set(profiles))
        if not targets:
            await query.message.reply_text("Select at least one profile first.")
            return
        for name in targets:
            delete_profile(name, user_id=uid)
            selected.discard(name)
        remaining = list_profiles(uid)
        await query.edit_message_text(
            _profiles_text(remaining, selected),
            parse_mode="HTML",
            reply_markup=_profiles_keyboard(remaining, selected),
        )
    elif data in {"quick_winpot", "visit_winpot_selected"}:
        profiles = list_profiles(uid)
        targets = sorted(selected & set(profiles))
        if data == "visit_winpot_selected" and not targets:
            await query.message.reply_text("Tap one or more profiles first to select them.")
            return
        targets = targets or (profiles[:1] if profiles else ["winpot"])
        settings = load_settings(uid)
        await _execute_visit(update, targets, settings.default_url)
    elif data == "confirm_bet_run":
        pending = context.user_data.pop("pending_automation", None)
        if not pending:
            await query.message.reply_text("No pending bet/automation to confirm.")
            return
        await _execute_automation(
            update,
            context,
            pending["profiles"],
            pending["url"],
            pending["goal"],
            confirmed=True,
        )
    elif data == "cancel_bet_run":
        context.user_data.pop("pending_automation", None)
        await query.edit_message_text("❌ Cancelled pending automation.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle reply keyboard buttons, interactive prompts, and natural-language requests."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if context.user_data.get("awaiting") == "access_token" and text not in {
        BTN_PROFILES,
        BTN_SETTINGS,
        BTN_HELP,
        BTN_QUICK_WINPOT,
    }:
        context.user_data.pop("awaiting", None)
        status = await verify_access_token(text)
        if not status.allowed:
            await update.message.reply_text(f"🔒 Token rejected: {status.reason}\nTry again or use /token <token>.")
            return
        set_access_token(text, _uid(update))
        await _delete_secret_message(update)
        await update.message.reply_text("✅ Access token verified and saved! Send /start to begin.")
        return

    if not await _require_access(update, context):
        return

    uid = _uid(update)
    if text == BTN_PROFILES:
        context.user_data.pop("awaiting", None)
        await profiles_cmd(update, context)
        return
    if text == BTN_SETTINGS:
        context.user_data.pop("awaiting", None)
        await settings_cmd(update, context)
        return
    if text == BTN_HELP:
        context.user_data.pop("awaiting", None)
        await help_cmd(update, context)
        return
    if text == BTN_QUICK_WINPOT:
        context.user_data.pop("awaiting", None)
        profiles = list_profiles(uid)
        selected = _get_selected_profiles(context)
        targets = sorted(selected & set(profiles)) or (profiles[:1] if profiles else ["winpot"])
        settings = load_settings(uid)
        await _execute_visit(update, targets, settings.default_url)
        return

    awaiting = context.user_data.pop("awaiting", None)
    if awaiting == "openrouter_api_key":
        settings = set_openrouter_api_key(text, uid)
        await _delete_secret_message(update)
        await update.message.reply_text(
            _settings_text(settings),
            parse_mode="HTML",
            reply_markup=_settings_keyboard(settings),
        )
        return
    if awaiting == "system_prompt":
        settings = set_system_prompt(text, uid)
        await update.message.reply_text(
            _settings_text(settings),
            parse_mode="HTML",
            reply_markup=_settings_keyboard(settings),
        )
        return
    if awaiting == "default_url":
        settings = set_default_url(text, uid)
        await update.message.reply_text(
            _settings_text(settings),
            parse_mode="HTML",
            reply_markup=_settings_keyboard(settings),
        )
        return
    if awaiting == "create_profile":
        try:
            path = create_profile(text, user_id=uid)
            await update.message.reply_text(f"✅ Created profile '{path.name}'.")
        except (ValueError, FileExistsError) as exc:
            await update.message.reply_text(str(exc))
        return

    saved = list_profiles(uid)
    selected_list = sorted(_get_selected_profiles(context) & set(saved))
    current_settings = load_settings(uid)
    try:
        routed = await route_message(
            text,
            selected_profiles=selected_list,
            saved_profiles=saved,
            api_key=current_settings.openrouter_api_key,
            custom_instructions=current_settings.system_prompt,
            default_url=current_settings.default_url,
        )
    except Exception as exc:
        logger.exception("Router failed")
        await update.message.reply_text(f"Could not process request: {exc}")
        return

    tool = routed["tool"]
    if tool == "visit":
        await _execute_visit(update, routed["profiles"], routed["url"])
    elif tool == "automate":
        await _execute_automation(update, context, routed["profiles"], routed["url"], routed["goal"])
    elif tool == "create_profile":
        try:
            path = create_profile(routed["name"], user_id=uid)
            await update.message.reply_text(f"✅ Created profile '{path.name}'.")
        except (ValueError, FileExistsError) as exc:
            await update.message.reply_text(str(exc))
    elif tool == "rename_profile":
        try:
            path = rename_profile(routed["old_name"], routed["new_name"], user_id=uid)
            await update.message.reply_text(f"✅ Renamed profile to '{path.name}'.")
        except (ValueError, FileNotFoundError, FileExistsError) as exc:
            await update.message.reply_text(str(exc))
    elif tool == "delete_profile":
        try:
            delete_profile(routed["name"], user_id=uid)
            await update.message.reply_text(f"🗑️ Deleted profile '{routed['name']}'.")
        except (ValueError, FileNotFoundError) as exc:
            await update.message.reply_text(str(exc))
    elif tool == "list_profiles":
        await profiles_cmd(update, context)
    elif tool == "update_settings":
        settings = load_settings(uid)
        for key in ("headless", "use_vision", "summary_mode", "confirm_before_bet", "max_concurrency"):
            if key in routed:
                setattr(settings, key, routed[key])
        save_settings(settings, uid)
        await update.message.reply_text(
            _settings_text(settings),
            parse_mode="HTML",
            reply_markup=_settings_keyboard(settings),
        )
    else:
        await update.message.reply_text(routed.get("message", "How can I help?"))


async def _post_init(application: Application) -> None:
    """Register bot commands in Telegram's native `/` menu."""
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Open main dashboard"),
            BotCommand("token", "Set your access token"),
            BotCommand("openrouter_key", "Set your OpenRouter API key"),
            BotCommand("profiles", "Manage & select browser profiles"),
            BotCommand("login", "Open visible browser to log in manually"),
            BotCommand("settings", "Customize all bot settings"),
            BotCommand("create_profile", "Create a new profile"),
            BotCommand("rename_profile", "Rename a profile"),
            BotCommand("delete_profile", "Delete a profile"),
            BotCommand("help", "Show usage help"),
        ]
    )


def main() -> None:
    """Start the Telegram bot."""
    load_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    ensure_chromium_installed()

    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("token", token_cmd))
    app.add_handler(CommandHandler("openrouter_key", openrouter_key_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("profiles", profiles_cmd))
    app.add_handler(CommandHandler("login", login_cmd))
    app.add_handler(CommandHandler("create_profile", create_profile_cmd))
    app.add_handler(CommandHandler("rename_profile", rename_profile_cmd))
    app.add_handler(CommandHandler("delete_profile", delete_profile_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram browser bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
