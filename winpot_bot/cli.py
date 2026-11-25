"""CLI runner for testing browser profile visits without Telegram."""

from __future__ import annotations

import argparse
import asyncio

from winpot_bot.bot import load_env
from winpot_bot.browser_manager import visit_with_profile
from winpot_bot.settings import load_settings
from winpot_bot.summarizer import summarize_page


async def _run(profile: str, url: str, headless: bool, summary_mode: str, api_key: str) -> None:
    page = await visit_with_profile(profile_name=profile, url=url, headless=headless)
    summary = await summarize_page(page, summary_mode=summary_mode, api_key=api_key)
    print(summary)


def main() -> None:
    """Parse CLI arguments and run a single profile visit."""
    load_env()
    settings = load_settings()

    parser = argparse.ArgumentParser(description="Visit a URL using a persistent browser profile.")
    parser.add_argument("--profile", required=True, help="Browser profile name")
    parser.add_argument("--url", required=True, help="Target URL to visit")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed (visible) mode",
    )
    args = parser.parse_args()

    headless = False if args.headed else settings.headless
    asyncio.run(_run(args.profile, args.url, headless, settings.summary_mode, settings.openrouter_api_key))


if __name__ == "__main__":
    main()
