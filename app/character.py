"""Character discovery: finds available character folders under assets/characters.

Each character is just a folder containing ``character.png``. This module
does not touch pixels (see ``image_processor``) - it only knows folder
layout, so character management stays simple and future characters can be
dropped in without code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import utils

logger = utils.get_logger("character")


@dataclass
class CharacterInfo:
    name: str
    source_png: Path


class CharacterManager:
    def __init__(self) -> None:
        self.characters_dir = utils.get_characters_dir()
        self._registry_path = utils.get_data_dir() / "characters.json"

    def list_characters(self) -> list[CharacterInfo]:
        found: list[CharacterInfo] = []
        if not self.characters_dir.exists():
            return found
        for folder in sorted(self.characters_dir.iterdir()):
            if not folder.is_dir():
                continue
            png = folder / "character.png"
            if png.exists():
                found.append(CharacterInfo(name=folder.name, source_png=png))
        return found

    def list_names(self) -> list[str]:
        names = [c.name for c in self.list_characters()]
        return names or ["default"]

    def get(self, name: str) -> CharacterInfo | None:
        png = self.characters_dir / name / "character.png"
        if png.exists():
            return CharacterInfo(name=name, source_png=png)
        return None

    def import_png(self, name: str, source_file: Path) -> CharacterInfo:
        """Copy a user-selected PNG into assets/characters/<name>/character.png."""
        import shutil

        dest_dir = self.characters_dir / name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "character.png"
        shutil.copy2(source_file, dest)
        logger.info("Imported new character '%s' from %s", name, source_file)
        self._update_registry(name)
        return CharacterInfo(name=name, source_png=dest)

    def _update_registry(self, name: str) -> None:
        registry = {}
        if self._registry_path.exists():
            try:
                registry = json.loads(self._registry_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                registry = {}
        registry.setdefault("characters", [])
        if name not in registry["characters"]:
            registry["characters"].append(name)
        self._registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
