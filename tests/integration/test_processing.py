"""End-to-end copy sanitization with generated public fixtures."""

import hashlib
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from PIL import Image, ImageCms, PngImagePlugin

from app.core.inspector import MetadataInspector
from app.core.models import ProcessingOptions, VerificationResult, VerificationState
from app.core.sanitizer import Sanitizer

SUCCESS = {VerificationState.PASSED, VerificationState.WARNINGS}


@pytest.mark.parametrize("fixture_name", ["jpeg_file", "png_file"])
def test_image_cleanup_preserves_original_and_pixels(
    request: pytest.FixtureRequest, fixture_name: str, tmp_path: Path
) -> None:
    source: Path = request.getfixturevalue(fixture_name)
    original = source.read_bytes()
    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "clean"))
    assert result.error is None, result.error
    assert result.output is not None
    assert result.verification.state in SUCCESS
    assert source.read_bytes() == original
    assert result.output != source
    with Image.open(source) as before, Image.open(result.output) as after:
        assert before.size == after.size
        assert before.convert("RGBA").tobytes() == after.convert("RGBA").tobytes()
    fields = MetadataInspector().inspect(result.output).fields
    assert not any("Private" in field.value or "Secret" in field.value for field in fields)
    assert not any(path.name.startswith(".metastrip") for path in result.output.parent.iterdir())


def test_collisions_never_overwrite(jpeg_file: Path, tmp_path: Path) -> None:
    options = ProcessingOptions(tmp_path / "clean")
    first = Sanitizer().process(jpeg_file, options)
    assert first.output is not None, first.error
    first_content = first.output.read_bytes()
    second = Sanitizer().process(jpeg_file, options)
    assert second.output is not None, second.error
    assert second.output != first.output
    assert first.output.read_bytes() == first_content


def test_png_cleanup_keeps_icc_bytes_but_removes_free_form_profile_name(tmp_path: Path) -> None:
    source = tmp_path / "profile.png"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    text = PngImagePlugin.PngInfo()
    text.add_text("Transparency", "Private text named like a technical tag")
    Image.new("RGB", (12, 9), "blue").save(source, icc_profile=profile, pnginfo=text)

    data = source.read_bytes()
    start = data.index(b"iCCP") - 4
    length = int.from_bytes(data[start : start + 4], "big")
    end = start + length + 12
    profile_payload = data[start + 8 : end - 4].split(b"\x00", 1)[1]
    private_name = b"Private Profile Label"
    chunk = b"iCCP" + private_name + b"\x00" + profile_payload
    original = (
        data[:start]
        + (len(chunk) - 4).to_bytes(4, "big")
        + chunk
        + zlib.crc32(chunk).to_bytes(4, "big")
        + data[end:]
    )
    source.write_bytes(original)

    result = Sanitizer().process(source, ProcessingOptions(tmp_path / "clean"))
    assert result.output is not None, result
    assert source.read_bytes() == original
    output = result.output.read_bytes()
    assert b"iCCPICC Profile\x00" + profile_payload in output
    assert private_name not in output
    with Image.open(source) as before, Image.open(result.output) as after:
        assert after.tobytes() == before.tobytes()
        assert after.info["icc_profile"] == profile
        assert not after.text


def test_concurrent_publication_never_overwrites(jpeg_file: Path, tmp_path: Path) -> None:
    options = ProcessingOptions(tmp_path / "clean")
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: Sanitizer().process(jpeg_file, options), range(3)))
    assert all(result.error is None for result in results), [result.error for result in results]
    outputs = {result.output for result in results}
    assert None not in outputs
    assert len(outputs) == 3
    assert len(list(options.output_dir.iterdir())) == 3


def test_same_directory_empty_suffix_cannot_overwrite(jpeg_file: Path) -> None:
    original = jpeg_file.read_bytes()
    result = Sanitizer().process(jpeg_file, ProcessingOptions(jpeg_file.parent, suffix=""))
    assert jpeg_file.read_bytes() == original
    if result.output:
        assert result.output != jpeg_file


def test_invalid_input_does_not_leave_outputs(tmp_path: Path) -> None:
    path = tmp_path / "invalid.jpg"
    path.write_bytes(b"not an image")
    destination = tmp_path / "clean"
    result = Sanitizer().process(path, ProcessingOptions(destination))
    assert result.error
    assert result.output is None
    assert not destination.exists() or not list(destination.iterdir())


def test_precancelled_job_has_no_output(jpeg_file: Path, tmp_path: Path) -> None:
    cancel = Event()
    cancel.set()
    destination = tmp_path / "clean"
    original_hash = hashlib.sha256(jpeg_file.read_bytes()).digest()
    result = Sanitizer().process(jpeg_file, ProcessingOptions(destination), cancel)
    assert result.cancelled
    assert result.output is None
    assert hashlib.sha256(jpeg_file.read_bytes()).digest() == original_hash
    assert not destination.exists() or not list(destination.iterdir())


def test_failed_verification_removes_temporary_copy(
    monkeypatch: pytest.MonkeyPatch, jpeg_file: Path, tmp_path: Path
) -> None:
    failed = VerificationResult(VerificationState.FAILED, remaining_fields=("EXIF:Artist",))
    monkeypatch.setattr("app.core.sanitizer.Verifier.verify", lambda *_args: failed)
    destination = tmp_path / "clean"
    result = Sanitizer().process(jpeg_file, ProcessingOptions(destination))
    assert result.error
    assert result.output is None
    assert result.verification.remaining_fields == ("EXIF:Artist",)
    assert not list(destination.iterdir())


def test_cancellation_after_cleaning_discards_temporary_copy(
    monkeypatch: pytest.MonkeyPatch, jpeg_file: Path, tmp_path: Path
) -> None:
    from app.core.image_cleaner import clean_image

    cancel = Event()

    def clean_then_cancel(*args) -> None:
        clean_image(*args)
        cancel.set()

    monkeypatch.setattr("app.core.sanitizer.clean_image", clean_then_cancel)
    destination = tmp_path / "clean"
    result = Sanitizer().process(jpeg_file, ProcessingOptions(destination), cancel)
    assert result.cancelled
    assert result.output is None
    assert not list(destination.iterdir())


def test_pdf_properties_removed_without_losing_readable_content(
    pdf_file: Path, tmp_path: Path
) -> None:
    import pymupdf

    original = pdf_file.read_bytes()
    result = Sanitizer().process(pdf_file, ProcessingOptions(tmp_path / "clean"))
    assert result.error is None, result.error
    assert result.output is not None
    assert pdf_file.read_bytes() == original
    with pymupdf.open(result.output) as document:
        assert not document.metadata.get("author")
        assert not document.metadata.get("title")
        assert not document.get_xml_metadata()
        assert document.embfile_count() == 0
        assert "Public document content" in document[0].get_text()
    assert result.verification.state in {VerificationState.WARNINGS, VerificationState.NOT_VERIFIED}
    assert result.verification.warnings


@pytest.mark.parametrize("remove_annotations", [True, False])
def test_pdf_annotation_cleanup_preserves_requested_appearance(
    tmp_path: Path,
    remove_annotations: bool,
) -> None:
    import pymupdf

    source = tmp_path / "annotated.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=200, height=200)
        page.insert_text((20, 40), "Readable content")
        note = page.add_text_annot((40, 80), "Private comment")
        note.set_info(title="Private title", subject="Private subject", modDate="D:20260201120000")
        document.xref_set_key(note.xref, "RC", "(Private rich text)")
        page.add_file_annot((80, 140), b"Private payload", "private.txt")
        document.save(source)
    with pymupdf.open(source) as document:
        page = document[0]
        note = next(page.annots())
        appearance = note.get_pixmap().samples
    original = source.read_bytes()
    result = Sanitizer().process(
        source,
        ProcessingOptions(
            tmp_path / "out",
            remove_pdf_annotations=remove_annotations,
        ),
    )
    assert result.error is None, result
    assert result.output is not None
    assert source.read_bytes() == original
    with pymupdf.open(result.output) as document:
        page = document[0]
        annotations = list(page.annots())
        if remove_annotations:
            assert not annotations
        else:
            [note] = annotations
            assert note.get_pixmap().samples == appearance
            metadata_keys = ("title", "content", "subject", "modDate", "id")
            assert all(not note.info[key] for key in metadata_keys)
            assert document.xref_get_key(note.xref, "RC")[0] == "null"


@pytest.mark.parametrize("user_password", ["", "viewer"])
def test_encrypted_pdf_is_refused_even_without_open_password(
    tmp_path: Path,
    user_password: str,
) -> None:
    import pymupdf

    source = tmp_path / "encrypted.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((30, 30), "Encrypted content")
        document.save(
            source, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw=user_password
        )
    with pymupdf.open(source) as document:
        assert bool(document.needs_pass) == bool(user_password)
    destination = tmp_path / "out"
    result = Sanitizer().process(source, ProcessingOptions(destination))
    assert result.verification.state == VerificationState.UNSUPPORTED
    assert result.output is None and not destination.exists()


def test_long_unicode_output_name_preserves_suffix_and_collision_safety(
    png_file: Path,
    tmp_path: Path,
) -> None:
    source = png_file.with_name("a" * 241 + "📷.png")
    source.write_bytes(png_file.read_bytes())
    options = ProcessingOptions(tmp_path / "out", suffix="_sanitized")
    first = Sanitizer().process(source, options)
    second = Sanitizer().process(source, options)
    assert first.output and second.output, (first, second)
    assert first.output.name.endswith("_sanitized.png")
    assert second.output.name.endswith("_sanitized (1).png")
    assert first.output.read_bytes() == second.output.read_bytes()
    with Image.open(source) as before, Image.open(second.output) as after:
        assert before.tobytes() == after.tobytes()
        assert not after.text
