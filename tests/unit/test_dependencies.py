"""Missing external tools should be explicit diagnostics, never auto-downloads."""

from pathlib import Path

import pytest
from PIL import Image

from app.core.models import ProcessingOptions
from app.core.sanitizer import Sanitizer
from app.utils import dependency_checker


def test_missing_dependencies_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependency_checker.shutil, "which", lambda _name: None)
    assert dependency_checker.check_dependencies() == {
        "exiftool": None,
        "ffmpeg": None,
        "ffprobe": None,
    }


def test_tiff_missing_exiftool_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dependency_checker.shutil, "which", lambda _name: None)
    source = tmp_path / "image.tif"
    Image.new("RGB", (8, 8)).save(source)
    original = source.read_bytes()
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "out"))
    assert result.error
    assert "exiftool" in result.error.lower()
    assert result.output is None
    assert source.read_bytes() == original
