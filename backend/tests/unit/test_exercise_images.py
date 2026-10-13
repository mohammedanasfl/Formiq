"""Exercise image paths (app.catalog.images): only an image file inside the
images directory is ever resolved, and the default directory is the backend's
own, wherever the process runs."""

from pathlib import Path

import pytest

from app.catalog.images import is_image_path, media_type, resolve_image
from app.core.config import BACKEND_DIR, Settings


@pytest.fixture
def images_dir(tmp_path):
    root = tmp_path / "exercise-images"
    (root / "Push_Up").mkdir(parents=True)
    (root / "Push_Up" / "0.jpg").write_bytes(b"\xff\xd8\xff jpeg")
    (root / "Push_Up" / "1.png").write_bytes(b"\x89PNG png")
    (tmp_path / "secret.jpg").write_bytes(b"outside")
    return root


@pytest.mark.parametrize("path", ["Push_Up/0.jpg", "3_4_Sit-Up/12.jpeg", "A/1.png", "A/2.webp"])
def test_an_image_path_has_one_shape(path):
    assert is_image_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "../secret.jpg",
        "Push_Up/../../secret.jpg",
        "/etc/passwd",
        "/Users/someone/0.jpg",
        "Push_Up/0.jpg/..",
        "Push_Up\\0.jpg",
        "Push_Up/0.gif",
        "Push_Up/0.svg",
        "Push_Up/image.jpg",
        "Push_Up/0.jpg\x00.png",
        "Push_Up",
        "",
        None,
        7,
    ],
)
def test_anything_else_is_not_an_image_path(images_dir, path):
    assert not is_image_path(path)
    if isinstance(path, str):
        assert resolve_image(images_dir, path) is None


def test_an_image_resolves_to_its_file_inside_the_directory(images_dir):
    file = resolve_image(images_dir, "Push_Up/0.jpg")

    assert file == (images_dir / "Push_Up" / "0.jpg").resolve()
    assert media_type(file) == "image/jpeg"
    assert media_type(resolve_image(images_dir, "Push_Up/1.png")) == "image/png"


def test_a_missing_file_resolves_to_nothing(images_dir):
    assert resolve_image(images_dir, "Push_Up/2.jpg") is None
    # a directory is not an image
    (images_dir / "Push_Up" / "3.jpg").mkdir()
    assert resolve_image(images_dir, "Push_Up/3.jpg") is None


def test_a_link_out_of_the_directory_resolves_to_nothing(images_dir, tmp_path):
    (images_dir / "Linked").mkdir()
    (images_dir / "Linked" / "0.jpg").symlink_to(tmp_path / "secret.jpg")
    (images_dir / "Escape").symlink_to(tmp_path)

    assert resolve_image(images_dir, "Linked/0.jpg") is None
    assert resolve_image(images_dir, "Escape/0.jpg") is None


def test_the_images_directory_is_the_backends_own_wherever_the_process_runs(monkeypatch, tmp_path):
    monkeypatch.delenv("EXERCISE_IMAGES_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x")

    assert settings.exercise_images_dir == BACKEND_DIR / "data" / "exercise-images"
    assert settings.exercise_images_dir.is_absolute()
    assert (settings.exercise_images_dir / "README.md").is_file()
    assert BACKEND_DIR == Path(__file__).resolve().parents[2]


def test_the_images_directory_can_be_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("EXERCISE_IMAGES_DIR", str(tmp_path))

    assert Settings(_env_file=None, database_url="postgresql+psycopg://x").exercise_images_dir == (
        tmp_path
    )
