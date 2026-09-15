"""First-launch experience: if no character exists yet, ask the user to
pick one full-body PNG before the pet can appear."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from .character import CharacterManager
from . import utils

logger = utils.get_logger("first_run")


def ensure_character_exists(parent: QWidget | None = None) -> bool:
    """Returns True once a usable character.png exists (default or imported)."""
    manager = CharacterManager()
    if manager.get("default") is not None:
        return True
    if manager.list_characters():
        return True

    QMessageBox.information(
        parent,
        "Welcome to Desktop Companion",
        "No character image was found yet.\n\n"
        "Please choose one full-body anime/illustration-style PNG "
        "(ideally with a transparent or simple background) to bring your "
        "desktop companion to life.",
    )

    file_path, _ = QFileDialog.getOpenFileName(
        parent, "Choose a character PNG", str(Path.home()), "PNG Images (*.png)"
    )
    if not file_path:
        logger.warning("User cancelled character selection on first run")
        return False

    manager.import_png("default", Path(file_path))
    return True
