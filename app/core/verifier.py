"""Verification of configured metadata checks and file readability."""

import hashlib
import math
from pathlib import Path
from threading import Event

from PIL import Image

from app.core.formats import detect_format
from app.core.inspector import MetadataInspector, _pymupdf, video_probe
from app.core.models import (
    FileFormat,
    InspectionResult,
    ProcessingOptions,
    VerificationResult,
    VerificationState,
)
from app.core.tools import check_cancel, run_tool, video_input_args
from app.utils.dependency_checker import check_dependencies


def image_fingerprint(
    path: Path,
    cancel: Event | None = None,
) -> tuple[tuple[int, int], str, str, int]:
    """Compare every decoded pixel, dimensions, mode and display orientation."""
    check_cancel(cancel)
    with Image.open(path) as image:
        image.load()
        digest = hashlib.sha256()
        displayed = hashlib.sha256()
        # Limit extra pixel buffers to roughly one MiB per RGBA band.
        rows = max(1, (1024 * 1024) // (4 * image.width))
        for top in range(0, image.height, rows):
            check_cancel(cancel)
            with image.crop((0, top, image.width, min(top + rows, image.height))) as band:
                digest.update(band.tobytes())
                with band.convert("RGBA") as rgba:
                    displayed.update(rgba.tobytes())
        digest.update(displayed.digest())
        return image.size, image.mode, digest.hexdigest(), int(image.getexif().get(274, 1))


class Verifier:
    def verify(
        self,
        before: InspectionResult,
        output: Path,
        options: ProcessingOptions,
        cancel: Event | None = None,
    ) -> VerificationResult:
        after = MetadataInspector().inspect(output, cancel)
        checks = [
            "Output readability",
            "Content-based format consistency",
            "Original and output metadata inspected",
            "Sensitive metadata field scan",
        ]
        notes = [*before.warnings, *after.warnings]
        remaining = tuple(field.name for field in after.fields if field.sensitive)
        if after.format != before.format or detect_format(output) != before.format:
            return VerificationResult(
                VerificationState.FAILED,
                tuple(checks),
                ("The output format changed unexpectedly.",),
            )
        if remaining:
            return VerificationResult(
                VerificationState.FAILED, tuple(checks), tuple(notes), remaining
            )
        if before.format in {FileFormat.JPEG, FileFormat.PNG, FileFormat.TIFF, FileFormat.WEBP}:
            if image_fingerprint(before.path, cancel) != image_fingerprint(output, cancel):
                return VerificationResult(
                    VerificationState.FAILED,
                    tuple(checks),
                    ("Decoded pixels or display orientation changed.",),
                )
            checks.append(
                "All decoded pixels, dimensions, color mode and display orientation unchanged"
            )
            with Image.open(before.path) as original, Image.open(output) as cleaned:
                expected = (
                    original.info.get("icc_profile") if options.preserve_color_profile else None
                )
                if cleaned.info.get("icc_profile") != expected:
                    return VerificationResult(
                        VerificationState.FAILED,
                        tuple(checks),
                        ("The color-profile preservation check failed.",),
                    )
                if expected:
                    notes.append(
                        "ICC color profile retained; profiles may contain identifying descriptions."
                    )
            checks.append("Configured ICC profile policy")
        elif before.format == FileFormat.PDF:
            if not self._pdf_equal(before.path, output, cancel):
                return VerificationResult(
                    VerificationState.FAILED,
                    tuple(checks),
                    ("PDF page content changed in the rendered comparison.",),
                )
            checks.append(
                "Page count and extracted text unchanged; all pages rendered at 36 DPI "
                "without annotations and render hashes match"
            )
            notes.append(
                "PDF checks are not complete anonymization; page content and arbitrary objects "
                "can identify authors."
            )
        else:
            if not self._video_equal(before.path, output, cancel):
                return VerificationResult(
                    VerificationState.FAILED,
                    tuple(checks),
                    ("Video stream integrity checks failed.",),
                )
            checks.append("Audio/video stream count, codecs and copied packet hashes unchanged")
        after_names = {item.name for item in after.fields}
        return VerificationResult(
            VerificationState.WARNINGS if notes else VerificationState.PASSED,
            tuple(checks),
            tuple(dict.fromkeys(notes)),
            removed_categories=tuple(
                sorted(
                    {
                        field.category
                        for field in before.fields
                        if field.sensitive and field.name not in after_names
                    }
                )
            ),
        )

    @staticmethod
    def _pdf_equal(source: Path, output: Path, cancel: Event | None) -> bool:
        pymupdf = _pymupdf()
        with pymupdf.open(source) as original, pymupdf.open(output) as cleaned:
            if original.page_count != cleaned.page_count:
                return False
            for first, second in zip(original, cleaned, strict=True):
                check_cancel(cancel)
                if first.rect != second.rect:
                    return False
                if first.get_text() != second.get_text():
                    return False
                one = first.get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5), annots=False)
                two = second.get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5), annots=False)
                if hashlib.sha256(one.samples).digest() != hashlib.sha256(two.samples).digest():
                    return False
        return True

    @staticmethod
    def _video_equal(source: Path, output: Path, cancel: Event | None) -> bool:
        original = video_probe(source, cancel)
        cleaned = video_probe(output, cancel)
        first = [(s.get("codec_type"), s.get("codec_name")) for s in original["streams"]]
        second = [(s.get("codec_type"), s.get("codec_name")) for s in cleaned["streams"]]
        if first != second:
            return False
        offsets = []
        for one, two in zip(original["streams"], cleaned["streams"], strict=True):
            for key in ("width", "height", "sample_rate", "channels"):
                if one.get(key) != two.get(key):
                    return False
            if "duration" in one and "duration" in two:
                first_duration, second_duration = float(one["duration"]), float(two["duration"])
                if (
                    not math.isfinite(first_duration)
                    or not math.isfinite(second_duration)
                    or abs(first_duration - second_duration) > 0.1
                ):
                    return False
            if "start_time" in one and "start_time" in two:
                shift = float(two["start_time"]) - float(one["start_time"])
                if not math.isfinite(shift):
                    return False
                offsets.append(shift)
        if offsets and max(offsets) - min(offsets) > 0.05:
            return False
        executable = check_dependencies()["ffmpeg"]
        if executable is None:
            return False
        hashes = []
        for path in (source, output):
            raw = run_tool(
                [
                    executable,
                    "-v",
                    "error",
                    "-nostdin",
                    *video_input_args(path),
                    "-map",
                    "0",
                    "-c",
                    "copy",
                    "-f",
                    "streamhash",
                    "-hash",
                    "sha256",
                    "-",
                ],
                cancel,
            )
            hashes.append(raw)
        return hashes[0] == hashes[1]


VerificationEngine = Verifier
