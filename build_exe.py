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
        "--collect-submodules",
        "winpot_bot",
        "--collect-submodules",
        "jev_ultrafast",
    ]
    for cfg in ("config.env", ".env"):
        cfg_file = ROOT / cfg
        if cfg_file.exists():
            cmd.extend(["--add-data", f"{cfg_file}{sep}."])

    cmd.append(str(ROOT / "winpot_bot" / "bot.py"))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
