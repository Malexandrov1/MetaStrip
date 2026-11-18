"""Extraction preserves useful categories without executing embedded values."""

import json
from pathlib import Path

import pytest
from PIL import Image

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


def test_exiftool_png_identifies_structure_without_exempting_text(
    png_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = {
        "PNG:Palette": "12 34 56",
        "PNG:Transparency": 0,
        "PNG:PNG-ICC_Profile:ProfileName": "ICC Profile",
        "PNG:PNG-TextualData:Transparency": "Sensitive transparency text",
        "PNG:PNG-TextualData:ImageWidth": "Sensitive width text",
        "PNG:PNG-TextualData:ProfileName": "ICC Profile",
    }

    def scan(_tool, options, _path, _cancel):
        assert "-G1:5" in options
        return json.dumps([record]).encode()

    monkeypatch.setattr("app.core.inspector.check_dependencies", lambda: {"exiftool": "tool"})
    monkeypatch.setattr("app.core.inspector.run_exiftool", scan)
    fields = MetadataInspector().inspect(png_file).fields
    assert {(f.name, f.value, f.sensitive) for f in fields if f.name.startswith("PNG:")} == {
        ("PNG:Palette", "12 34 56", False),
        ("PNG:Transparency", "0", False),
        ("PNG:ProfileName", "ICC Profile", False),
        ("PNG:Transparency", "Sensitive transparency text", True),
        ("PNG:ImageWidth", "Sensitive width text", True),
        ("PNG:ProfileName", "ICC Profile", True),
    }


def test_exiftool_webp_flags_and_alpha_structure_are_technical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "alpha.webp"
    Image.new("RGBA", (4, 4), (10, 20, 30, 120)).save(path)
    record = {
        "RIFF:RIFF-VP8X:WebP_Flags": "Alpha",
        "RIFF:RIFF-ALPH:AlphaPreprocessing": "Level Reduction",
        "RIFF:RIFF-ALPH:AlphaFiltering": "Horizontal",
        "RIFF:RIFF-ALPH:AlphaCompression": "Lossless",
        "XMP-dc:RIFF-XMP:AlphaFiltering": "Private text",
    }
    monkeypatch.setattr("app.core.inspector.check_dependencies", lambda: {"exiftool": "tool"})
    monkeypatch.setattr(
        "app.core.inspector.run_exiftool", lambda *_args: json.dumps([record]).encode()
    )
    fields = MetadataInspector().inspect(path).fields
    assert {f.name for f in fields if f.name.startswith("RIFF:") and not f.sensitive} == {
        "RIFF:WebP_Flags",
        "RIFF:AlphaPreprocessing",
        "RIFF:AlphaFiltering",
        "RIFF:AlphaCompression",
    }
    assert any(f.name == "XMP-dc:AlphaFiltering" and f.sensitive for f in fields)


def test_pdf_metadata(pdf_file: Path) -> None:
    result = MetadataInspector().inspect(pdf_file)
    assert any("Private PDF Author" in field.value for field in result.fields)


def test_malformed_image_fails_safely(tmp_path: Path) -> None:
    path = tmp_path / "broken.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"invalid data")
    with pytest.raises(MetaStripError):
        MetadataInspector().inspect(path)
