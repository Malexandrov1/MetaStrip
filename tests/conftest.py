"""Small synthetic fixtures; no user files or network access are required."""

import os
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def jpeg_file(tmp_path: Path) -> Path:
    path = tmp_path / "camera photo.jpg"
    image = Image.new("RGB", (24, 16), (30, 100, 180))
    exif = Image.Exif()
    exif[271] = "Private Camera Manufacturer"
    exif[272] = "Private Camera Model"
    exif[305] = "Secret Editing Software"
    exif[315] = "Private Photographer"
    exif[306] = "2025:01:02 03:04:05"
    image.save(path, exif=exif, quality=90)
    return path


@pytest.fixture
def png_file(tmp_path: Path) -> Path:
    path = tmp_path / "private screenshot.png"
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Private PNG Author")
    info.add_text("Comment", "Private PNG Comment")
    info.add_itxt("Description", "Private International Text")
    info.add_text("Software", "Secret PNG Software", zip=True)
    Image.new("RGBA", (24, 16), (10, 80, 150, 128)).save(path, pnginfo=info)
    return path


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    import pymupdf

    path = tmp_path / "private document.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=200, height=200)
        page.insert_text((20, 40), "Public document content")
        document.set_metadata({"author": "Private PDF Author", "title": "Private PDF Title"})
        document.set_xml_metadata(
            '<?xml version="1.0"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
            "Private XMP Payload</x:xmpmeta>"
        )
        document.embfile_add("secret.txt", b"Private embedded payload")
        document.save(path)
    return path
