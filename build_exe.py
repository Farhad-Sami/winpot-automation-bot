"""Build a standalone single-file executable for the current OS using PyInstaller."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "winpot-bot",
        "--add-data",
        f"{ROOT / 'jev_ultrafast' / 'snapshot.js'}{sep}jev_ultrafast",
        "--collect-all",
        "playwright",
        "--hidden-import",
        "winpot_bot",
        "--hidden-import",
        "jev_ultrafast.model",
    ]
    env_file = ROOT / ".env"
    if env_file.exists():
        cmd.extend(["--add-data", f"{env_file}{sep}."])

    cmd.append(str(ROOT / "winpot_bot" / "bot.py"))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
