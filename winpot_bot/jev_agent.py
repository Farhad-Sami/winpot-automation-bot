"""Multi-step browser automation loop reusing jev_ultrafast's snapshot.js & action_space."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright

from jev_ultrafast.model import action_space
from winpot_bot.ai import extract_json, openrouter_chat
from winpot_bot.browser_manager import PageContent, get_profile_dir
from winpot_bot.paths import bundle_dir

SNAPSHOT_JS_PATH = bundle_dir() / "jev_ultrafast" / "snapshot.js"
MAX_STEPS = 15
MIN_WAIT_SECONDS = 1
MAX_WAIT_SECONDS = 30
DEFAULT_WAIT_SECONDS = 3


@dataclass(slots=True)
class AutomationResult:
    """Outcome of a multi-step browser automation run."""

    profile_name: str
    goal: str
    status: str  # "done", "blocked", "max_steps"
    final_page: PageContent
    steps: list[str] = field(default_factory=list)


def validate_decision(
    decision: dict[str, Any],
    targets: dict[str, dict[str, dict[str, Any]]],
    controls: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Validate operation and target against observed elements and controls."""
    op = str(decision.get("operation", "")).strip().upper()
    valid_ops = set(targets) | set(controls) | {"WAIT", "DONE", "BLOCKED"}
    if op not in valid_ops:
        raise ValueError(f"Unsupported operation '{op}'.")

    target = decision.get("target")
    if op in targets:
        target_str = str(target).strip() if target is not None else ""
        if target_str not in targets[op]:
            raise ValueError(f"Invalid target '{target_str}' for operation '{op}'.")
        target = target_str
    else:
        target = None

    wait_seconds = DEFAULT_WAIT_SECONDS
    if op == "WAIT":
        try:
            wait_seconds = int(round(float(decision.get("wait_seconds", DEFAULT_WAIT_SECONDS))))
        except (TypeError, ValueError):
            wait_seconds = DEFAULT_WAIT_SECONDS
        wait_seconds = max(MIN_WAIT_SECONDS, min(MAX_WAIT_SECONDS, wait_seconds))

    return {
        "operation": op,
        "target": target,
        "wait_seconds": wait_seconds,
        "reason": str(decision.get("reason", "")).strip()[:200],
    }


async def decide_next_step(
    snapshot: dict[str, Any],
    goal: str,
    history: list[str],
    api_key: str = "",
    screenshot_b64: str | None = None,
    custom_instructions: str = "",
    dry_run_before_submit: bool = False,
) -> tuple[dict[str, Any], dict[str, dict[str, dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Ask the decision model for the next bounded operation and target."""
    elements, targets, controls = action_space(snapshot["actions"])
    valid_ops = sorted(set(targets) | set(controls) | {"WAIT", "DONE", "BLOCKED"})

    model = (
        os.getenv("AI_MODEL_DECISIONS_API")
        or os.getenv("AI_MODEL_DECISION")
        or os.getenv("AI_MODEL")
        or "typesafe/jev-1.14"
    ).strip()

    state_summary = {
        "goal": goal,
        "url": snapshot["url"],
        "title": snapshot["title"],
        "visible_text": snapshot["text"][:3500],
        "elements": elements[:120],
        "valid_operations": valid_ops,
        "recent_steps": history[-8:],
    }

    system_prompt = (
        "You are a precise browser automation decision engine. "
        "Choose ONE next operation from valid_operations to achieve the user's goal.\n"
        "Return ONLY valid JSON with keys:\n"
        '- "operation": one of valid_operations\n'
        '- "target": element index string (required for CLICK, TYPE_TEXT, SELECT; null otherwise)\n'
        '- "wait_seconds": integer 1-30 (only when operation is WAIT; default 3)\n'
        '- "reason": brief 1-sentence reason\n'
        "Use WAIT if the goal asks to wait on the page or content is still loading. "
        "Use DONE when the goal is satisfied. Use BLOCKED if impossible."
    )
    if dry_run_before_submit:
        system_prompt += (
            "\n\nSAFETY RULE: Do NOT click any final 'Place Bet', 'Confirm', or 'Submit' button. "
            "Stop with DONE once the betslip/form is filled and ready for final confirmation."
        )
    if custom_instructions.strip():
        system_prompt += f"\n\nStanding instructions:\n{custom_instructions.strip()}"

    text_block = json.dumps(state_summary, ensure_ascii=False)
    user_content: list[dict[str, Any]] | str = (
        [
            {"type": "text", "text": text_block},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screenshot_b64}"}},
        ]
        if screenshot_b64
        else text_block
    )

    raw = await openrouter_chat(
        model=model,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        api_key=api_key,
        timeout=35.0,
    )
    validated = validate_decision(extract_json(raw), targets, controls)
    return validated, targets, controls


async def generate_field_text(goal: str, action: dict[str, Any], snapshot: dict[str, Any], api_key: str = "") -> str:
    """Use AI_MODEL_TEXT to generate the text value for a TYPE_TEXT target."""
    model = (os.getenv("AI_MODEL_TEXT") or os.getenv("AI_MODEL") or "mistralai/mistral-nemo").strip()
    raw = await openrouter_chat(
        model=model,
        api_key=api_key,
        messages=[
            {
                "role": "system",
                "content": (
                    'Return ONLY valid JSON: {"value": "..."} containing the exact text to type '
                    "into the specified field based on the user's goal."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "goal": goal,
                        "field_label": action.get("label", ""),
                        "current_value": action.get("value", ""),
                        "url": snapshot["url"],
                        "title": snapshot["title"],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    return str(extract_json(raw).get("value", ""))


async def _execute_action(
    page: Page,
    decision: dict[str, Any],
    targets: dict[str, dict[str, dict[str, Any]]],
    controls: dict[str, dict[str, Any]],
    goal: str,
    snapshot: dict[str, Any],
    api_key: str = "",
) -> str:
    """Execute a validated decision on the Playwright page and return a step description."""
    op = decision["operation"]

    if op == "WAIT":
        secs = decision["wait_seconds"]
        await page.wait_for_timeout(secs * 1000)
        return f"WAIT {secs}s"

    if op in controls:
        delta = int(controls[op].get("delta", 560))
        await page.evaluate("(d) => window.scrollBy(0, d)", delta)
        await page.wait_for_timeout(400)
        return f"{op}"

    action = targets[op][decision["target"]]
    node_id = action["node"]

    if op == "CLICK":
        rect = await page.evaluate(
            """(nid) => {
                const el = window.__jevFast?.nodes?.get(nid);
                if (!el || !el.isConnected) return null;
                const r = el.getBoundingClientRect();
                return {x: r.x + r.width / 2, y: r.y + r.height / 2};
            }""",
            node_id,
        )
        if not rect:
            raise RuntimeError(f"Target element [{decision['target']}] is no longer on the page.")
        await page.mouse.click(rect["x"], rect["y"])
        await page.wait_for_timeout(1000)
        return f"CLICK [{decision['target']}] {action['label']}"

    if op == "TYPE_TEXT":
        text_val = await generate_field_text(goal, action, snapshot, api_key=api_key)
        ok = await page.evaluate(
            """([nid, val]) => {
                const el = window.__jevFast?.nodes?.get(nid);
                if (!el || !el.isConnected) return false;
                el.focus();
                if ('value' in el) {
                    el.value = val;
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                } else if (el.isContentEditable) {
                    el.innerText = val;
                    el.dispatchEvent(new InputEvent('input', {bubbles: true}));
                }
                return true;
            }""",
            [node_id, text_val],
        )
        if not ok:
            raise RuntimeError(f"Input element [{decision['target']}] is no longer on the page.")
        await page.wait_for_timeout(500)
        return f"TYPE_TEXT [{decision['target']}] {action['label']}"

    if op == "SELECT":
        ok = await page.evaluate(
            """([nid, val]) => {
                const el = window.__jevFast?.nodes?.get(nid);
                if (!el || !el.isConnected) return false;
                el.value = val;
                el.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
            }""",
            [node_id, action["value"]],
        )
        if not ok:
            raise RuntimeError(f"Select element [{decision['target']}] is no longer on the page.")
        await page.wait_for_timeout(500)
        return f"SELECT [{decision['target']}] {action['label']}"

    return op


async def run_automation(
    profile_name: str,
    url: str,
    goal: str,
    api_key: str = "",
    headless: bool = True,
    use_vision: bool = False,
    custom_instructions: str = "",
    dry_run_before_submit: bool = False,
    base_dir: Path | None = None,
    max_steps: int = MAX_STEPS,
) -> AutomationResult:
    """Run a multi-step Jev automation loop using a persistent Playwright profile."""
    profile_dir = get_profile_dir(profile_name, base_dir=base_dir)
    target_url = url.strip()
    if not target_url.startswith(("http://", "https://")):
        target_url = f"https://{target_url}"

    snapshot_js = SNAPSHOT_JS_PATH.read_text(encoding="utf-8")
    steps: list[str] = []
    status = "max_steps"

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

            for _ in range(max_steps):
                snapshot = await page.evaluate(snapshot_js)
                if not snapshot:
                    status = "blocked"
                    break

                screenshot_b64 = None
                if use_vision:
                    raw_img = await page.screenshot(type="jpeg", quality=70)
                    screenshot_b64 = base64.b64encode(raw_img).decode("ascii")

                decision, targets, controls = await decide_next_step(
                    snapshot=snapshot,
                    goal=goal,
                    history=steps,
                    api_key=api_key,
                    screenshot_b64=screenshot_b64,
                    custom_instructions=custom_instructions,
                    dry_run_before_submit=dry_run_before_submit,
                )
                op = decision["operation"]
                if op in {"DONE", "BLOCKED"}:
                    status = op.lower()
                    if decision["reason"]:
                        steps.append(f"{op}: {decision['reason']}")
                    break

                step_desc = await _execute_action(
                    page, decision, targets, controls, goal, snapshot, api_key=api_key
                )
                steps.append(step_desc)

            title = (await page.title()).strip()
            final_url = page.url
            raw_text = await page.evaluate(
                """() => document.body ? (document.body.innerText || '').trim() : ''"""
            )
            cleaned_text = re.sub(r"\n{3,}", "\n\n", raw_text).strip()
            final_page = PageContent(
                profile_name=profile_dir.name,
                requested_url=target_url,
                final_url=final_url,
                title=title,
                meta_description="",
                text=cleaned_text,
            )
            return AutomationResult(
                profile_name=profile_dir.name,
                goal=goal,
                status=status,
                final_page=final_page,
                steps=steps,
            )
        finally:
            await context.close()


async def run_automations(
    profile_names: list[str],
    url: str,
    goal: str,
    api_key: str = "",
    headless: bool = True,
    use_vision: bool = False,
    custom_instructions: str = "",
    dry_run_before_submit: bool = False,
    base_dir: Path | None = None,
    max_concurrency: int = 5,
) -> list[AutomationResult | tuple[str, Exception]]:
    """Run `run_automation` across multiple profiles with bounded concurrency."""
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(name: str) -> AutomationResult | tuple[str, Exception]:
        async with semaphore:
            try:
                return await run_automation(
                    profile_name=name,
                    url=url,
                    goal=goal,
                    api_key=api_key,
                    headless=headless,
                    use_vision=use_vision,
                    custom_instructions=custom_instructions,
                    dry_run_before_submit=dry_run_before_submit,
                    base_dir=base_dir,
                )
            except Exception as exc:
                return (name, exc)

    return list(await asyncio.gather(*(_run_one(name) for name in profile_names)))
