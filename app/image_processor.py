"""Turns one user-supplied full-body PNG into the assets the pet needs.

Responsibilities: load, best-effort background removal, alpha-preserving
crop, resize, generate a horizontally-flipped ("facing left") variant, and
cache the results to disk so this expensive work only happens once per
character (or whenever the source file changes, detected via mtime).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import utils

logger = utils.get_logger("image_processor")

TARGET_HEIGHT = 220  # px, before the user-configurable "scale" is applied


@dataclass
class ProcessedCharacter:
    name: str
    right_facing_path: Path
    left_facing_path: Path
    width: int
    height: int


def _remove_flat_background(img: Image.Image, tolerance: int = 18) -> Image.Image:
    """Best-effort background removal for characters that ship without alpha.

    If the source already has real transparency (any pixel with alpha < 250),
    it is left untouched - we never fight an artist's existing alpha channel.
    Otherwise we flood-fill-style clear pixels near the four corners' color,
    which handles the common case of a flat white/solid-color backdrop.
    This is intentionally conservative: it never touches the character's
    own appearance, only pixels close to the sampled corner color.
    """
    img = img.convert("RGBA")
    pixels = img.getdata()
    has_real_alpha = any(p[3] < 250 for p in pixels)
    if has_real_alpha:
        return img

    w, h = img.size
    corners = [img.getpixel((0, 0)), img.getpixel((w - 1, 0)),
               img.getpixel((0, h - 1)), img.getpixel((w - 1, h - 1))]
    # Use the most common corner color as the presumed background.
    bg = max(set(corners), key=corners.count)

    new_pixels = []
    for p in pixels:
        r, g, b = p[0], p[1], p[2]
        if (abs(r - bg[0]) <= tolerance and abs(g - bg[1]) <= tolerance and abs(b - bg[2]) <= tolerance):
            new_pixels.append((r, g, b, 0))
        else:
            new_pixels.append(p)
    img.putdata(new_pixels)
    return img


def _autocrop(img: Image.Image, padding: int = 6) -> Image.Image:
    """Crop transparent padding down to the character's bounding box."""
    bbox = img.getbbox()
    if bbox is None:
        return img
    left, top, right, bottom = bbox
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(img.width, right + padding)
    bottom = min(img.height, bottom + padding)
    return img.crop((left, top, right, bottom))


def _resize_to_target_height(img: Image.Image, target_height: int = TARGET_HEIGHT) -> Image.Image:
    if img.height == 0:
        return img
    ratio = target_height / img.height
    new_size = (max(1, int(img.width * ratio)), target_height)
    return img.resize(new_size, Image.LANCZOS)


class ImageProcessor:
    """Loads a character.png, processes it, and caches right/left facing PNGs."""

    def __init__(self) -> None:
        self.cache_dir = utils.get_cache_dir()

    def _cache_paths(self, character_name: str) -> tuple[Path, Path, Path]:
        char_cache = self.cache_dir / character_name
        char_cache.mkdir(parents=True, exist_ok=True)
        return (
            char_cache / "right.png",
            char_cache / "left.png",
            char_cache / "meta.json",
        )

    def process(self, character_name: str, source_path: Path, force: bool = False) -> ProcessedCharacter | None:
        if not source_path.exists():
            logger.error("Character source image missing: %s", source_path)
            return None

        right_path, left_path, meta_path = self._cache_paths(character_name)
        source_mtime = source_path.stat().st_mtime

        if not force and right_path.exists() and left_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("source_mtime") == source_mtime:
                    with Image.open(right_path) as cached:
                        w, h = cached.size
                    return ProcessedCharacter(character_name, right_path, left_path, w, h)
            except (OSError, ValueError, json.JSONDecodeError):
                pass  # fall through and reprocess

        try:
            with Image.open(source_path) as img:
                img.load()
                processed = _remove_flat_background(img)
                processed = _autocrop(processed)
                processed = _resize_to_target_height(processed)
                flipped = processed.transpose(Image.FLIP_LEFT_RIGHT)

                processed.save(right_path, "PNG")
                flipped.save(left_path, "PNG")
                meta_path.write_text(
                    json.dumps({"source_mtime": source_mtime, "size": processed.size}),
                    encoding="utf-8",
                )
                logger.info("Processed character '%s' -> %s", character_name, processed.size)
                return ProcessedCharacter(character_name, right_path, left_path, *processed.size)
        except Exception:  # noqa: BLE001 - a bad image must never crash the app
            logger.exception("Failed to process character image: %s", source_path)
            return None
