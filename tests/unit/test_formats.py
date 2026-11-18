"""File identification must use bytes instead of trusting the extension."""

from pathlib import Path

import pytest
from PIL import Image

from app.core.formats import detect_format
from app.core.models import FileFormat, MetaStripError


@pytest.mark.parametrize(
    ("pillow_format", "expected"),
    [
        ("JPEG", FileFormat.JPEG),
        ("PNG", FileFormat.PNG),
        ("TIFF", FileFormat.TIFF),
        ("WEBP", FileFormat.WEBP),
    ],
)
def test_content_detection_ignores_extension(
    tmp_path: Path, pillow_format: str, expected: FileFormat
) -> None:
    path = tmp_path / "misleading.pdf"
    Image.new("RGB", (8, 8), "blue").save(path, format=pillow_format)
    assert detect_format(path) == expected


def test_pdf_detection(pdf_file: Path) -> None:
    assert detect_format(pdf_file) == FileFormat.PDF


@pytest.mark.parametrize("payload", [b"", b"ordinary text", b"PK\x03\x04fake archive"])
def test_unsupported_content_rejected(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "fake.jpg"
    path.write_bytes(payload)
    with pytest.raises(MetaStripError):
        detect_format(path)


def test_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises((MetaStripError, OSError)):
        detect_format(tmp_path / "missing.png")
