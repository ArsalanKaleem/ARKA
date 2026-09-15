"""Shared utility helpers: filesystem paths and logging setup.

Centralizing path resolution here means every other module can ask
`utils.get_data_dir()` / `utils.get_assets_dir()` instead of hardcoding
locations, which keeps the app portable and avoids hardcoded absolute
Windows paths anywhere else in the codebase.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def get_app_root() -> Path:
    """Return the directory the application is running from.

    Works both when run as a plain script (``python main.py``) and when
    frozen into a single executable by PyInstaller (``sys.frozen``).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """Directory for logs, config, and cached/processed characters."""
    data_dir = get_app_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_assets_dir() -> Path:
    assets_dir = get_app_root() / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir


def get_characters_dir() -> Path:
    chars_dir = get_assets_dir() / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    return chars_dir


def get_cache_dir() -> Path:
    cache_dir = get_data_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_config_path() -> Path:
    return get_app_root() / "config.json"


_LOGGER_CONFIGURED = False


def setup_logging() -> logging.Logger:
    """Configure the root application logger.

    Logs to ``data/app.log`` and, when not frozen, also to stdout so
    developers see output while iterating. Safe to call multiple times.
    """
    global _LOGGER_CONFIGURED
    logger = logging.getLogger("desktop_companion")
    if _LOGGER_CONFIGURED:
        return logger

    logger.setLevel(logging.INFO)
    log_path = get_data_dir() / "app.log"

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)

    if not getattr(sys, "frozen", False):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(stream_handler)

    _LOGGER_CONFIGURED = True
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the app's configured root logger."""
    setup_logging()
    return logging.getLogger(f"desktop_companion.{name}")
