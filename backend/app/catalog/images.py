"""Exercise image paths: relative to the exercise images directory, and never
anything a request supplies.

A stored path has one fixed shape, an exercise directory and a numbered image
file, so it can hold no "..", no absolute path and no other file type; and it
is served only when it resolves to a file inside the images directory.
"""

import re
from pathlib import Path

# "<upstream exercise id>/<n>.<image type>", as the upstream records list them
IMAGE_PATH = re.compile(r"[0-9A-Za-z_-]{1,100}/[0-9]{1,3}\.(?:jpg|jpeg|png|webp)")

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def is_image_path(path: object) -> bool:
    """Whether the path has the one shape an image path may have."""
    return isinstance(path, str) and IMAGE_PATH.fullmatch(path) is not None


def resolve_image(images_dir: Path, path: str) -> Path | None:
    """The image file the path names, or None when the path has another shape,
    leads outside the images directory (through a link, say) or names no
    file."""
    if not is_image_path(path):
        return None
    root = images_dir.resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root) or not file.is_file():
        return None
    return file


def media_type(file: Path) -> str:
    return MEDIA_TYPES[file.suffix.lower()]
