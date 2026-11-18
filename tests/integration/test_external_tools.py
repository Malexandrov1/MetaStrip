"""Real tool integrations; skip clearly when a local executable is unavailable."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageCms, TiffImagePlugin

from app.core.inspector import MetadataInspector
from app.core.models import ProcessingOptions, VerificationState
from app.core.sanitizer import Sanitizer
from app.core.verifier import image_fingerprint
from app.utils.dependency_checker import check_dependencies

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("preserve_icc", [True, False])
def test_tiff_cleanup_with_exiftool(tmp_path: Path, preserve_icc: bool) -> None:
    if not check_dependencies()["exiftool"]:
        pytest.skip("ExifTool is not installed locally")
    source = tmp_path / "камера & 日本.tif"
    info = TiffImagePlugin.ImageFileDirectory_v2()
    info[315] = "Private TIFF Author"
    info[270] = "Private TIFF Description"
    info[274] = 6
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    image = Image.new("RGB", (16, 12), (40, 80, 120))
    image.putpixel((1, 2), (220, 20, 50))
    image.save(source, tiffinfo=info, icc_profile=profile)
    original = source.read_bytes()
    result = Sanitizer().process(
        source, ProcessingOptions(tmp_path / "résultats 日本", preserve_color_profile=preserve_icc)
    )
    assert result.error is None, result
    assert result.output is not None
    assert source.read_bytes() == original
    assert image_fingerprint(source) == image_fingerprint(result.output)
    with Image.open(result.output) as cleaned:
        assert cleaned.info.get("icc_profile") == (profile if preserve_icc else None)
    assert not any(
        "Private TIFF" in field.value for field in MetadataInspector().inspect(result.output).fields
    )


def test_tiff_palette_survives_exiftool_cleanup(tmp_path: Path) -> None:
    if not check_dependencies()["exiftool"]:
        pytest.skip("ExifTool is not installed locally")
    source = tmp_path / "palette.tiff"
    image = Image.new("P", (16, 12), 1)
    image.putpalette([10, 20, 30, 180, 190, 200] + [0] * 762)
    info = TiffImagePlugin.ImageFileDirectory_v2()
    info[315] = "Private TIFF Author"
    image.save(source, tiffinfo=info)
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "out"))
    assert result.output is not None, result
    with Image.open(result.output) as cleaned:
        assert not cleaned.getexif().get(315)
        assert cleaned.convert("RGB").getpixel((2, 2)) == (180, 190, 200)


@pytest.mark.parametrize("extension", ["mp4", "mov"])
def test_video_metadata_stream_copy(tmp_path: Path, extension: str) -> None:
    dependencies = check_dependencies()
    if not dependencies["ffmpeg"] or not dependencies["ffprobe"]:
        pytest.skip("FFmpeg and ffprobe are required for video integration")
    source = tmp_path / f"клип & 日本.{extension}"
    brand = ["-brand", "iso6"] if extension == "mp4" else []
    subprocess.run(
        [
            dependencies["ffmpeg"],
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=5:d=0.4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.4",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            *brand,
            "-metadata",
            "title=Private Video Title",
            "-metadata",
            "artist=Private Video Author",
            str(source),
        ],
        check=True,
        timeout=30,
        capture_output=True,
        shell=False,
    )
    original = source.read_bytes()
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "out"))
    assert result.error is None, result.error
    assert result.output is not None
    assert result.verification.state in {VerificationState.PASSED, VerificationState.WARNINGS}
    assert source.read_bytes() == original
    assert not any(
        "Private Video" in field.value
        for field in MetadataInspector().inspect(result.output).fields
    )
