"""Format-specific processing, verification and transactional output publication."""

import re
import shutil
from pathlib import Path
from threading import Event

from PIL import Image

from app.core.exiftool import run_exiftool
from app.core.file_manager import file_digest, publish_output, temporary_output, validate_suffix
from app.core.formats import detect_format
from app.core.image_cleaner import clean_image
from app.core.inspector import MetadataInspector, _pymupdf, video_probe
from app.core.models import (
    CancelledError,
    DependencyError,
    FileFormat,
    InspectionResult,
    MetaStripError,
    ProcessingOptions,
    ProcessingResult,
    UnsupportedFormatError,
    VerificationResult,
    VerificationState,
)
from app.core.tools import check_cancel, run_tool, video_input_args
from app.core.verifier import Verifier
from app.utils.dependency_checker import check_dependencies

_EXTENSIONS = {
    FileFormat.JPEG: {".jpg", ".jpeg", ".jpe"},
    FileFormat.PNG: {".png"},
    FileFormat.TIFF: {".tif", ".tiff"},
    FileFormat.WEBP: {".webp"},
    FileFormat.PDF: {".pdf"},
    FileFormat.MP4: {".mp4", ".m4v"},
    FileFormat.MOV: {".mov"},
}


class Sanitizer:
    def process(
        self, path: Path, options: ProcessingOptions, cancel: Event | None = None
    ) -> ProcessingResult:
        path = Path(path)
        format_: FileFormat | None = None
        try:
            check_cancel(cancel)
            validate_suffix(options.suffix)
            format_ = detect_format(path)
            path = path.resolve()
            if path.suffix.lower() not in _EXTENSIONS[format_]:
                raise MetaStripError(
                    "The filename extension does not match the detected format. "
                    "Rename a copy with the correct extension before cleaning."
                )
            source_digest = file_digest(path, cancel)
            before = MetadataInspector().inspect(path, cancel)
            check_cancel(cancel)
            directory = Path(options.output_dir).resolve()
            with temporary_output(directory, path.suffix) as temporary:
                if format_ in {FileFormat.JPEG, FileFormat.PNG, FileFormat.WEBP}:
                    clean_image(path, temporary, format_, options.preserve_color_profile)
                elif format_ == FileFormat.TIFF:
                    self._tiff(before, temporary, options, cancel)
                elif format_ == FileFormat.PDF:
                    self._pdf(path, temporary, options, cancel)
                else:
                    self._video(path, temporary, cancel)
                check_cancel(cancel)
                verification = Verifier().verify(before, temporary, options, cancel)
                check_cancel(cancel)
                if file_digest(path, cancel) != source_digest:
                    raise MetaStripError(
                        "The original changed during processing; output was discarded."
                    )
                if verification.state not in {VerificationState.PASSED, VerificationState.WARNINGS}:
                    return ProcessingResult(
                        path,
                        format=format_,
                        verification=verification,
                        error="Output did not pass the configured verification checks.",
                    )
                check_cancel(cancel)
                output = publish_output(temporary, path, directory, options.suffix)
                return ProcessingResult(path, output, format_, verification)
        except CancelledError as exc:
            return ProcessingResult(path, format=format_, error=str(exc), cancelled=True)
        except UnsupportedFormatError as exc:
            return ProcessingResult(
                path,
                format=format_,
                error=str(exc),
                verification=VerificationResult(VerificationState.UNSUPPORTED),
            )
        except MetaStripError as exc:
            return ProcessingResult(
                path,
                format=format_,
                error=str(exc),
                verification=VerificationResult(VerificationState.FAILED),
            )
        except Exception:
            # Corrupt parsers and OS failures must not leak metadata in exception strings.
            return ProcessingResult(
                path,
                format=format_,
                error="Processing failed: unreadable file, unsafe structure or filesystem error.",
                verification=VerificationResult(VerificationState.FAILED),
            )

    @staticmethod
    def _tiff(
        before: InspectionResult,
        output: Path,
        options: ProcessingOptions,
        cancel: Event | None,
    ) -> None:
        executable = check_dependencies()["exiftool"]
        if executable is None:
            raise DependencyError(
                "TIFF sanitization requires ExifTool on PATH or METASTRIP_EXIFTOOL."
            )
        with Image.open(before.path) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise UnsupportedFormatError("Multi-page TIFF sanitization is not yet supported.")
        shutil.copyfile(before.path, output)
        # ExifTool retains the primary TIFF image directory with -all=.
        private_ifd_tags = [
            f"-{field.name}="
            for field in before.fields
            if field.sensitive and re.fullmatch(r"IFD0:[A-Za-z][A-Za-z0-9_]*", field.name)
        ]
        args = [
            "-overwrite_original",
            "-all=",
            *private_ifd_tags,
            "-tagsFromFile",
            "@",
            "-Orientation",
        ]
        if options.preserve_color_profile:
            args.append("-ICC_Profile")
        run_exiftool(executable, args, output, cancel)

    @staticmethod
    def _pdf(source: Path, output: Path, options: ProcessingOptions, cancel: Event | None) -> None:
        pymupdf = _pymupdf()
        with pymupdf.open(source) as document:
            if document.needs_pass or document.metadata.get("encryption") or document.is_repaired:
                raise UnsupportedFormatError(
                    "Encrypted or damaged PDFs cannot be safely sanitized."
                )
            if document.is_form_pdf:
                raise UnsupportedFormatError(
                    "PDFs containing forms or signatures are not supported."
                )
            for index in range(1, document.xref_length()):
                check_cancel(cancel)
                if not document.xref_object(index, compressed=False).lstrip().startswith("<<"):
                    continue
                keys = set(document.xref_get_keys(index))
                active_keys = {"JS", "JavaScript", "AA", "OpenAction", "RichMediaContent"}
                action = document.xref_get_key(index, "S")[1] if "S" in keys else ""
                object_type = document.xref_get_key(index, "Type")[1] if "Type" in keys else ""
                if (
                    keys & active_keys
                    or action in {"/JavaScript", "/Launch", "/RichMediaExecute"}
                    or object_type == "/Sig"
                ):
                    raise UnsupportedFormatError(
                        "PDFs with active actions or signatures cannot be safely sanitized."
                    )
            document.set_metadata({})
            document.del_xml_metadata()
            document.xref_set_key(-1, "ID", "null")
            for name in document.embfile_names():
                document.embfile_del(name)
            for page in document:
                check_cancel(cancel)
                for annotation in list(page.annots() or []):
                    if options.remove_pdf_annotations or annotation.type[0] == 17:
                        page.delete_annot(annotation)
                if not options.remove_pdf_annotations:
                    # Preserve appearance, but clear annotation author/comment properties.
                    for annotation in page.annots() or []:
                        for key in ("T", "Contents", "Subj", "CreationDate", "M", "NM", "RC"):
                            document.xref_set_key(annotation.xref, key, "null")
            # An incremental save would leave prior revisions in the file.
            document.save(str(output), garbage=4, deflate=True, clean=True, no_new_id=True)

    @staticmethod
    def _video(source: Path, output: Path, cancel: Event | None) -> None:
        executable = check_dependencies()["ffmpeg"]
        if executable is None:
            raise DependencyError(
                "Video sanitization requires FFmpeg and ffprobe installed locally."
            )
        probe = video_probe(source, cancel)
        if any(stream.get("codec_type") not in {"video", "audio"} for stream in probe["streams"]):
            raise UnsupportedFormatError(
                "Video files with subtitle, data or attachment streams are not supported."
            )
        args = [
            executable,
            "-v",
            "error",
            "-nostdin",
            "-y",
            *video_input_args(source),
            "-map",
            "0",
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            "-map_metadata:s",
            "-1",
            "-map_chapters",
            "-1",
            "-metadata",
            "creation_time=",
            "-metadata",
            "encoder=",
        ]
        for index, _ in enumerate(probe["streams"]):
            args.extend(
                [
                    f"-metadata:s:{index}",
                    "creation_time=",
                    f"-metadata:s:{index}",
                    "encoder=",
                    f"-metadata:s:{index}",
                    "handler_name=",
                    f"-metadata:s:{index}",
                    "language=und",
                ]
            )
        run_tool([*args, str(output)], cancel, timeout=600)
