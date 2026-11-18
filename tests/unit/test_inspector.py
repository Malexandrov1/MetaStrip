"""Extraction preserves useful categories without executing embedded values."""

from pathlib import Path

import pytest

from app.core.inspector import MetadataInspector
from app.core.models import MetaStripError


def test_jpeg_metadata(jpeg_file: Path) -> None:
    result = MetadataInspector().inspect(jpeg_file)
    values = " ".join(field.value for field in result.fields)
    assert "Private Photographer" in values
    assert "Private Camera Model" in values
    assert all(field.category for field in result.fields)


def test_png_metadata(png_file: Path) -> None:
    result = MetadataInspector().inspect(png_file)
    assert any("Private PNG Author" in field.value for field in result.fields)


def test_pdf_metadata(pdf_file: Path) -> None:
    result = MetadataInspector().inspect(pdf_file)
    assert any("Private PDF Author" in field.value for field in result.fields)


def test_malformed_image_fails_safely(tmp_path: Path) -> None:
    path = tmp_path / "broken.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"invalid data")
    with pytest.raises(MetaStripError):
        MetadataInspector().inspect(path)
