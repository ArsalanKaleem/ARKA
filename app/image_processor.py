"""Turns one user-supplied full-body PNG into the assets the pet needs.

Two things get produced and cached per character:

1. A plain processed image (bg removed, autocropped, resized) — used as-is
   for states that don't need moving limbs (idle, sleep, notice, ...).
2. A simple two-legged "cutout rig": the same image torn into a torso
   layer (legs masked out) and two leg layers (torso masked out, and
   masked to one half each), all sharing one canvas size and one pivot
   point at the hip line. Rotating the two leg layers by opposite angles
   around that shared pivot and re-compositing them under the torso is
   the same trick behind cheap 2D cutout/puppet rigs (Adobe Character
   Animator, DragonBones, paper-doll animation): pin joints, rotate
   layers, no per-frame artwork needed.

Arms are deliberately NOT cut out the same way. Segmenting arms
reliably from an arbitrary photo (holding a bag, hands in pockets, folded
arms, etc.) is unreliable and tends to produce a visibly broken cutout;
instead the torso layer gets a small synced shear in ``pet.py`` to imply
counter-swinging shoulders without risking that failure mode. See the
README's "How the animation actually works" section.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from . import utils

logger = utils.get_logger("image_processor")

TARGET_HEIGHT = 220  # px, before the user-configurable "scale" is applied
HIP_FRACTION = 0.50  # fraction of character height where the legs begin
LEG_OVERLAP_FRACTION = 0.07  # how far each leg layer reaches past hip-center, to hide the seam


@dataclass
class RigAssets:
    """Torso + two leg layers, all the same canvas size, sharing one pivot."""

    torso_path: Path
    leg_a_path: Path
    leg_b_path: Path
    pivot_x: int
    pivot_y: int


@dataclass
class ProcessedCharacter:
    name: str
    right_facing_path: Path
    left_facing_path: Path
    width: int
    height: int
    rig_right: RigAssets
    rig_left: RigAssets


def _remove_flat_background(img: Image.Image, tolerance: int = 18) -> Image.Image:
    """Best-effort background removal for characters that ship without alpha.

    If the source already has real transparency (any pixel with alpha < 250),
    it is left untouched - we never fight an artist's existing alpha channel.
    Otherwise we clear pixels close to the most common corner color, which
    handles a flat white/solid-color backdrop but NOT a busy photo
    background (see the app's docs on preparing source images).
    """
    img = img.convert("RGBA")
    pixels = img.getdata()
    has_real_alpha = any(p[3] < 250 for p in pixels)
    if has_real_alpha:
        return img

    w, h = img.size
    corners = [img.getpixel((0, 0)), img.getpixel((w - 1, 0)),
               img.getpixel((0, h - 1)), img.getpixel((w - 1, h - 1))]
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


def _mask_to_box(img: Image.Image, keep_box: tuple[int, int, int, int]) -> Image.Image:
    """Return a same-size copy of ``img`` with everything outside ``keep_box`` cleared."""
    w, h = img.size
    x0, y0, x1, y1 = keep_box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle([x0, y0, x1 - 1, y1 - 1], fill=255)
    transparent = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return Image.composite(img, transparent, mask)


def _build_rig(img: Image.Image, hip_fraction: float = HIP_FRACTION,
               overlap_fraction: float = LEG_OVERLAP_FRACTION) -> tuple[Image.Image, Image.Image, Image.Image, int, int]:
    """Tear one character image into (torso, leg_a, leg_b, pivot_x, pivot_y).

    ``leg_a``/``leg_b`` are not "left"/"right" in the anatomical sense -
    they're just the two halves split at the character's horizontal
    center, each kept a bit past center so a small swing angle doesn't
    reveal a gap at the hip. Both share the same pivot point, so at
    rotation 0 they recombine into pixel-for-pixel the original image.
    """
    w, h = img.size
    hip_y = int(h * hip_fraction)

    bbox = img.getbbox()
    center_x = (bbox[0] + bbox[2]) // 2 if bbox else w // 2
    overlap = max(2, int(w * overlap_fraction))

    torso = _mask_to_box(img, (0, 0, w, hip_y))
    leg_a = _mask_to_box(img, (0, hip_y, min(w, center_x + overlap), h))
    leg_b = _mask_to_box(img, (max(0, center_x - overlap), hip_y, w, h))

    return torso, leg_a, leg_b, center_x, hip_y


class ImageProcessor:
    """Loads a character.png, processes it, and caches the plain image + rig."""

    def __init__(self) -> None:
        self.cache_dir = utils.get_cache_dir()

    def _paths(self, character_name: str) -> dict[str, Path]:
        char_cache = self.cache_dir / character_name
        char_cache.mkdir(parents=True, exist_ok=True)
        names = [
            "right", "left",
            "right_torso", "right_leg_a", "right_leg_b",
            "left_torso", "left_leg_a", "left_leg_b",
        ]
        paths = {n: char_cache / f"{n}.png" for n in names}
        paths["meta"] = char_cache / "meta.json"
        return paths

    def process(self, character_name: str, source_path: Path, force: bool = False) -> ProcessedCharacter | None:
        if not source_path.exists():
            logger.error("Character source image missing: %s", source_path)
            return None

        paths = self._paths(character_name)
        source_mtime = source_path.stat().st_mtime

        if not force and paths["meta"].exists() and all(paths[n].exists() for n in paths if n != "meta"):
            try:
                meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
                if meta.get("source_mtime") == source_mtime and "pivot_right" in meta:
                    with Image.open(paths["right"]) as cached:
                        w, h = cached.size
                    return ProcessedCharacter(
                        name=character_name,
                        right_facing_path=paths["right"],
                        left_facing_path=paths["left"],
                        width=w,
                        height=h,
                        rig_right=RigAssets(paths["right_torso"], paths["right_leg_a"], paths["right_leg_b"], *meta["pivot_right"]),
                        rig_left=RigAssets(paths["left_torso"], paths["left_leg_a"], paths["left_leg_b"], *meta["pivot_left"]),
                    )
            except (OSError, ValueError, json.JSONDecodeError, KeyError):
                pass  # fall through and reprocess

        try:
            with Image.open(source_path) as img:
                img.load()
                processed = _remove_flat_background(img)
                processed = _autocrop(processed)
                processed = _resize_to_target_height(processed)
                flipped = processed.transpose(Image.FLIP_LEFT_RIGHT)

                processed.save(paths["right"], "PNG")
                flipped.save(paths["left"], "PNG")

                r_torso, r_leg_a, r_leg_b, r_px, r_py = _build_rig(processed)
                l_torso, l_leg_a, l_leg_b, l_px, l_py = _build_rig(flipped)

                r_torso.save(paths["right_torso"], "PNG")
                r_leg_a.save(paths["right_leg_a"], "PNG")
                r_leg_b.save(paths["right_leg_b"], "PNG")
                l_torso.save(paths["left_torso"], "PNG")
                l_leg_a.save(paths["left_leg_a"], "PNG")
                l_leg_b.save(paths["left_leg_b"], "PNG")

                paths["meta"].write_text(
                    json.dumps(
                        {
                            "source_mtime": source_mtime,
                            "size": processed.size,
                            "pivot_right": [r_px, r_py],
                            "pivot_left": [l_px, l_py],
                        }
                    ),
                    encoding="utf-8",
                )
                logger.info("Processed character '%s' -> %s (rig pivot y=%d)", character_name, processed.size, r_py)

                return ProcessedCharacter(
                    name=character_name,
                    right_facing_path=paths["right"],
                    left_facing_path=paths["left"],
                    width=processed.width,
                    height=processed.height,
                    rig_right=RigAssets(paths["right_torso"], paths["right_leg_a"], paths["right_leg_b"], r_px, r_py),
                    rig_left=RigAssets(paths["left_torso"], paths["left_leg_a"], paths["left_leg_b"], l_px, l_py),
                )
        except Exception:  # noqa: BLE001 - a bad image must never crash the app
            logger.exception("Failed to process character image: %s", source_path)
            return None
