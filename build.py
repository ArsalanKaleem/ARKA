"""Builds a single-file, windowless Windows executable with PyInstaller.

Run with:  python build.py
Output:    dist/DesktopCompanion.exe
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    if not sys.platform.startswith("win"):
        print("Note: building on non-Windows will still produce a binary for THIS platform, "
              "not a .exe. Run this on Windows to build the real Windows executable.")

    assets_sep = ";" if sys.platform.startswith("win") else ":"

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",  # no console window
        "--name", "DesktopCompanion",
        f"--add-data=assets{assets_sep}assets",
        "main.py",
    ]

    print("Running:", " ".join(args))
    result = subprocess.run(args, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    print("\nBuild complete: dist/DesktopCompanion.exe")
    print("Note: config.json and data/ are created next to the executable on first run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
