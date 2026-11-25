"""Manage persistent Playwright browser profiles and page visits."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from playwright._impl._driver import compute_driver_executable, get_driver_env
from playwright.async_api import async_playwright

from winpot_bot.paths import app_dir

logger = logging.getLogger(__name__)

PROFILES_DIR = app_dir() / "profiles"
PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


def validate_url(url: str) -> str:
    """Ensure URL uses http(s) and does not target local/private network addresses."""
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("URL cannot be empty.")
    if "://" not in cleaned:
        first_part = cleaned.split("/", 1)[0]
        if ":" in first_part and not re.match(r"^[a-zA-Z0-9.-]+:\d+$", first_part):
            raise ValueError("Unsupported URL scheme. Only http/https allowed.")
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Only http/https allowed.")
    host = (parsed.hostname or "").strip().lower()
    if not host or host in BLOCKED_HOSTS or host.endswith(".local"):
        raise ValueError("Access to local/internal hostnames is blocked.")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Access to private or internal IP addresses is blocked.")
    except ValueError as exc:
        if "blocked" in str(exc):
            raise
    return cleaned


def ensure_chromium_installed() -> None:
    """Install Playwright's Chromium browser if it is not already downloaded."""
    driver_exec, driver_cli = compute_driver_executable()
    env = get_driver_env()
    logger.info("Checking Playwright Chromium installation...")
    subprocess.run([driver_exec, driver_cli, "install", "chromium"], env=env, check=True)


@dataclass(slots=True)
class PageContent:
    """Extracted content from a visited web page."""

    profile_name: str
    requested_url: str
    final_url: str
    title: str
    meta_description: str
    text: str


def is_headless() -> bool:
    """Return whether the browser should run in headless mode based on HEADLESS env."""
    return os.getenv("HEADLESS", "true").strip().lower() not in {"0", "false", "no"}


def sanitize_profile_name(name: str) -> str:
    """Validate and return a safe browser profile name."""
    cleaned = name.strip()
    if not PROFILE_NAME_RE.fullmatch(cleaned) or cleaned.lower() == "all":
        raise ValueError(
            "Invalid profile name. Use 1-64 characters: letters, numbers, '-' or '_' (and not 'all')."
        )
    return cleaned


def _profiles_root(user_id: int | str = "default", base_dir: Path | None = None) -> Path:
    return (base_dir or PROFILES_DIR) / str(user_id)


def get_profile_dir(
    profile_name: str,
    user_id: int | str = "default",
    base_dir: Path | None = None,
) -> Path:
    """Return (and create if missing) the persistent user-data directory for a profile."""
    safe_name = sanitize_profile_name(profile_name)
    profile_dir = _profiles_root(user_id, base_dir) / safe_name
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir


def create_profile(
    profile_name: str,
    user_id: int | str = "default",
    base_dir: Path | None = None,
) -> Path:
    """Create a new empty profile directory, raising FileExistsError if it already exists."""
    safe_name = sanitize_profile_name(profile_name)
    profile_dir = _profiles_root(user_id, base_dir) / safe_name
    if profile_dir.exists():
        raise FileExistsError(f"Profile '{safe_name}' already exists.")
    profile_dir.mkdir(parents=True, exist_ok=False)
    return profile_dir


def delete_profile(
    profile_name: str,
    user_id: int | str = "default",
    base_dir: Path | None = None,
) -> None:
    """Delete an existing profile directory, raising FileNotFoundError if missing."""
    safe_name = sanitize_profile_name(profile_name)
    profile_dir = _profiles_root(user_id, base_dir) / safe_name
    if not profile_dir.exists():
        raise FileNotFoundError(f"Profile '{safe_name}' does not exist.")
    shutil.rmtree(profile_dir)


def rename_profile(
    old_name: str,
    new_name: str,
    user_id: int | str = "default",
    base_dir: Path | None = None,
) -> Path:
    """Rename an existing profile directory."""
    safe_old = sanitize_profile_name(old_name)
    safe_new = sanitize_profile_name(new_name)
    root = _profiles_root(user_id, base_dir)
    old_dir = root / safe_old
    new_dir = root / safe_new
    if not old_dir.exists():
        raise FileNotFoundError(f"Profile '{safe_old}' does not exist.")
    if new_dir.exists():
        raise FileExistsError(f"Profile '{safe_new}' already exists.")
    old_dir.rename(new_dir)
    return new_dir


def list_profiles(user_id: int | str = "default", base_dir: Path | None = None) -> list[str]:
    """List existing browser profile names for `user_id`."""
    root = _profiles_root(user_id, base_dir)
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and PROFILE_NAME_RE.fullmatch(p.name))


async def visit_with_profile(
    profile_name: str,
    url: str,
    headless: bool = True,
    user_id: int | str = "default",
    base_dir: Path | None = None,
    timeout_ms: int = 30000,
) -> PageContent:
    """Launch or reuse a persistent browser profile, visit `url`, and extract page content."""
    target_url = validate_url(url)
    profile_dir = get_profile_dir(profile_name, user_id=user_id, base_dir=base_dir)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Allow dynamic client-side content a brief moment to settle.
            await page.wait_for_timeout(1500)

            title = (await page.title()).strip()
            final_url = page.url
            meta_description = await page.evaluate(
                """() => {
                    const el = document.querySelector('meta[name="description"]');
                    return el ? (el.getAttribute('content') || '').trim() : '';
                }"""
            )
            raw_text = await page.evaluate(
                """() => document.body ? (document.body.innerText || '').trim() : ''"""
            )
            cleaned_text = re.sub(r"\n{3,}", "\n\n", raw_text).strip()

            return PageContent(
                profile_name=profile_dir.name,
                requested_url=target_url,
                final_url=final_url,
                title=title,
                meta_description=meta_description,
                text=cleaned_text,
            )
        finally:
            await context.close()


async def open_profile_for_login(
    profile_name: str,
    url: str = "https://www.winpot.mx/sport",
    user_id: int | str = "default",
    base_dir: Path | None = None,
) -> Path:
    """Open a visible browser window for manual login and wait until the user closes it."""
    target_url = validate_url(url)
    profile_dir = get_profile_dir(profile_name, user_id=user_id, base_dir=base_dir)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
        )
        closed = asyncio.Event()
        context.on("close", lambda *_: closed.set())
        page = context.pages[0] if context.pages else await context.new_page()
        page.on("close", lambda *_: closed.set() if not context.pages else None)
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        await closed.wait()
    return profile_dir


async def visit_with_profiles(
    profile_names: list[str],
    url: str,
    headless: bool = True,
    user_id: int | str = "default",
    base_dir: Path | None = None,
    max_concurrency: int = 3,
) -> list[PageContent | tuple[str, Exception]]:
    """Run `visit_with_profile` across multiple profiles with bounded concurrency."""
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _run_one(name: str) -> PageContent | tuple[str, Exception]:
        async with semaphore:
            try:
                return await visit_with_profile(
                    profile_name=name,
                    url=url,
                    headless=headless,
                    user_id=user_id,
                    base_dir=base_dir,
                )
            except Exception as exc:
                return (name, exc)

    return list(await asyncio.gather(*(_run_one(name) for name in profile_names)))
