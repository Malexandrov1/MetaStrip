"""MPF declarations must be distinguished from JPEG images actually in the file."""

import hashlib
import io
import os
import struct
from pathlib import Path

import pytest
from PIL import Image

from app.core.inspector import MetadataInspector
from app.core.jpeg_structure import STALE_MPF_WARNING, jpeg_frame_info
from app.core.models import MetaStripError, ProcessingOptions, VerificationState
from app.core.sanitizer import Sanitizer


def _jpeg() -> bytes:
    output = io.BytesIO()
    exif = Image.Exif()
    exif[271] = "Private Camera"
    exif[315] = "Private Photographer"
    Image.new("RGB", (12, 10), (30, 80, 160)).save(output, "JPEG", exif=exif)
    return output.getvalue()


def _segment(marker: int, payload: bytes) -> bytes:
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload


def _stale_mpf(jpeg: bytes, secondary_offset: int = 4_000_000, order: str = "<") -> bytes:
    # Original APP2 retained after replacing the primary and removing its trailer.
    tiff = b"II*\x00" if order == "<" else b"MM\x00*"
    tiff += struct.pack(order + "I", 8) + struct.pack(order + "H", 3)
    tiff += struct.pack(order + "HHI4s", 0xB000, 7, 4, b"0100")
    tiff += struct.pack(order + "HHII", 0xB001, 4, 1, 2)
    tiff += struct.pack(order + "HHII", 0xB002, 7, 32, 50)
    tiff += struct.pack(order + "I", 0)
    tiff += struct.pack(order + "IIIHH", 0x030000, 4_000_000, 0, 0, 0)
    tiff += struct.pack(order + "IIIHH", 0, 10_000, secondary_offset, 0, 0)
    return jpeg[:2] + _segment(0xE2, b"MPF\x00" + tiff) + jpeg[2:]


def _assert_clean_copy(source: Path, directory: Path) -> None:
    original = source.read_bytes()
    result = Sanitizer().process(source, ProcessingOptions(directory))
    assert result.error is None, result.error
    assert result.output is not None
    assert result.verification.state in {VerificationState.PASSED, VerificationState.WARNINGS}
    assert source.read_bytes() == original
    with Image.open(source) as before, Image.open(result.output) as after:
        before.load()
        after.load()
        assert before.tobytes() == after.tobytes()
        assert before.size == after.size
        assert before.getexif().get(274, 1) == after.getexif().get(274, 1)
        assert after.format == "JPEG"
        assert getattr(after, "n_frames", 1) == 1
        assert not after.getexif().get(271)
        assert not after.getexif().get(315)
        assert "mp" not in after.info
        assert "xmp" not in after.info
    inspected = MetadataInspector().inspect(result.output)
    assert not [field for field in inspected.fields if field.sensitive]
    assert not any(path.name.startswith(".metastrip-") for path in directory.iterdir())


@pytest.mark.parametrize("order", ["<", ">"])
def test_stale_mpf_count_does_not_mean_two_present_frames(tmp_path: Path, order: str) -> None:
    source = tmp_path / "sample.jpg"
    source.write_bytes(_stale_mpf(_jpeg(), order=order))
    with Image.open(source) as image:
        assert image.format == "MPO"
        assert image.n_frames == 2
        image.load()
        with pytest.raises((OSError, ValueError)):
            image.seek(1)
            image.load()
    frames = jpeg_frame_info(source.read_bytes())
    assert frames.declared_frames == 2
    assert frames.stale_index
    inspection = MetadataInspector().inspect(source)
    assert STALE_MPF_WARNING in inspection.warnings
    assert next(field.value for field in inspection.fields if field.name == "Image:Frames") == "1"
    _assert_clean_copy(source, tmp_path / "clean")
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "again"))
    assert STALE_MPF_WARNING in result.verification.warnings


@pytest.mark.parametrize("ultra_hdr", [False, True])
def test_real_mpo_is_rejected_even_when_pillow_exposes_one_frame(
    tmp_path: Path, ultra_hdr: bool
) -> None:
    output = io.BytesIO()
    Image.new("RGB", (12, 10), "red").save(
        output, "MPO", save_all=True, append_images=[Image.new("RGB", (12, 10), "blue")]
    )
    data = output.getvalue()
    if ultra_hdr:
        # Pillow's Ultra HDR exception returns a JPEG without n_frames, despite MPF=2.
        data = data[:2] + _segment(0xE1, b'Example hdrgm:Version="1.0"') + data[2:]
    source = tmp_path / "real.jpg"
    source.write_bytes(data)
    with Image.open(source) as image:
        assert getattr(image, "n_frames", 1) == (1 if ultra_hdr else 2)
    assert not jpeg_frame_info(data).stale_index
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "clean"))
    assert result.error and "Multi-picture JPEG" in result.error
    assert result.output is None
    assert source.read_bytes() == data
    assert not list((tmp_path / "clean").iterdir())


@pytest.mark.parametrize("offset", [0, 1, 200])
def test_overlapping_or_partly_present_mpf_entries_are_rejected(
    tmp_path: Path, offset: int
) -> None:
    source = tmp_path / "ambiguous.jpg"
    source.write_bytes(_stale_mpf(_jpeg(), offset))
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "clean"))
    assert result.error
    assert result.output is None


def test_stale_mpf_with_trailing_data_is_not_silently_flattened(tmp_path: Path) -> None:
    source = tmp_path / "trailer.jpg"
    source.write_bytes(_stale_mpf(_jpeg()) + b"unclassified image trailer")
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "clean"))
    assert result.error and result.output is None


def test_incomplete_primary_is_not_accepted_as_stale_mpf(tmp_path: Path) -> None:
    source = tmp_path / "truncated.jpg"
    source.write_bytes(_stale_mpf(_jpeg())[:-2])
    with pytest.raises(MetaStripError, match="incomplete JPEG"):
        jpeg_frame_info(source.read_bytes())
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "clean"))
    assert result.error and result.output is None


def test_malformed_mpf_is_not_treated_as_a_stale_index(tmp_path: Path) -> None:
    data = _stale_mpf(_jpeg())
    # Corrupt the IFD offset, while retaining the complete primary codestream.
    data = data[:14] + b"\xff" * 4 + data[18:]
    with pytest.raises(MetaStripError, match="Malformed MPF"):
        jpeg_frame_info(data)


def test_duplicate_mpf_indexes_are_refused(tmp_path: Path) -> None:
    data = _stale_mpf(_jpeg())
    segment_end = 4 + int.from_bytes(data[4:6], "big")
    data = data[:2] + data[2:segment_end] + data[2:]
    source = tmp_path / "duplicate.jpg"
    source.write_bytes(data)
    with pytest.raises(MetaStripError, match="Multiple MPF"):
        jpeg_frame_info(data)
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "clean"))
    assert result.error and result.output is None


def test_embedded_jpeg_thumbnail_is_not_a_second_frame(tmp_path: Path) -> None:
    jpeg = _jpeg()
    # A complete nested JPEG (with its own SOI/EOI) within a length-delimited APP segment.
    source = tmp_path / "preview.jpg"
    source.write_bytes(jpeg[:2] + _segment(0xED, b"Private preview" + jpeg) + jpeg[2:])
    assert jpeg_frame_info(source.read_bytes()).declared_frames == 1
    _assert_clean_copy(source, tmp_path / "clean")


@pytest.mark.parametrize("format_", ["PNG", "WEBP", "TIFF"])
def test_other_multiframe_formats_remain_unsupported(tmp_path: Path, format_: str) -> None:
    source = tmp_path / f"animated.{format_.lower()}"
    Image.new("RGB", (12, 10), "red").save(
        source, format_, save_all=True, append_images=[Image.new("RGB", (12, 10), "blue")]
    )
    original = source.read_bytes()
    with Image.open(source) as image:
        assert image.n_frames == 2
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "clean"))
    assert result.error and result.output is None
    assert source.read_bytes() == original


@pytest.mark.integration
def test_original_exiftool_apple_sample(tmp_path: Path) -> None:
    sample = os.environ.get("METASTRIP_APPLE_SAMPLE")
    if not sample:
        pytest.skip("Set METASTRIP_APPLE_SAMPLE to the official Apple_iPhone15ProMax.jpg")
    source = Path(sample)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        "840c8c862c41b690ca4400cce7c061f6ec65ae55550171d421af5fdd2c100ee5"
    )
    assert source.stat().st_size == 5663
    assert jpeg_frame_info(source.read_bytes()).stale_index
    _assert_clean_copy(source, tmp_path / "clean")
