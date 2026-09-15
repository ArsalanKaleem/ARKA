"""Optional Windows startup registration.

Uses the current-user ``HKCU\\...\\Run`` registry key rather than the
Startup folder or a scheduled task: it requires no admin privileges, no
extra dependency (``winreg`` ships with CPython on Windows), and is easy
to cleanly add/remove. No-ops (and logs) on non-Windows platforms so the
rest of the app keeps working during development on other OSes.
"""

from __future__ import annotations

import sys

from . import utils

logger = utils.get_logger("startup")

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "DesktopCompanion"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{utils.get_app_root() / "main.py"}"'


def is_windows() -> bool:
    return sys.platform.startswith("win")


def is_enabled() -> bool:
    if not is_windows():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """Returns True on success; never raises, since this is a "nice to have"."""
    if not is_windows():
        logger.info("Start-with-Windows is a no-op on this platform")
        return False

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
                logger.info("Registered start-with-Windows entry")
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                    logger.info("Removed start-with-Windows entry")
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        logger.exception("Failed to update start-with-Windows registry entry")
        return False
