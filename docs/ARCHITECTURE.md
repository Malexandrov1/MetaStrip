# MetaStrip architecture

The desktop interface depends on immutable contracts in `app/core/models.py`.
Core services never import Qt. Processing runs in Qt workers, with signals carrying
results back to the GUI thread. Files and metadata never leave the machine.

## Service contracts

- `formats.detect_format(path: Path) -> FileFormat`: content-based identification.
- `inspector.MetadataInspector().inspect(path: Path,
  cancel: threading.Event | None = None) -> InspectionResult`.
- `sanitizer.Sanitizer().process(path: Path, options: ProcessingOptions,
  cancel: threading.Event | None = None) -> ProcessingResult`.
- `utils.dependency_checker.check_dependencies() -> dict[str, str | None]`:
  executable paths or null for missing tools; keys `exiftool`, `ffmpeg`, `ffprobe`.
- All expected failures are returned as `ProcessingResult.error` or raised as
  `MetaStripError` during inspection. Cancellation is cooperative and never commits
  an incomplete output. Original files are never edited.

Only `Passed configured checks` and `Passed with warnings` permit publication.
Unsupported, failed, and incomplete verification never publish a sanitized output.
Publication uses Windows rename, which refuses an existing destination, or an
exclusive hard link on POSIX. Temporary files reside on the destination volume.
Decoded image samples, palette transparency, dimensions, mode, orientation and
the configured ICC policy are verified independently of metadata filtering.

## Processing strategies

ExifTool provides independent metadata inspection. Image cleanup must retain
compressed image data where possible. PDF processing uses a complete rewritten
document, with explicit limits on anonymization. Video processing uses FFmpeg
stream copying and separately checks stream and container tags.

MetaStrip is distributed under AGPL-3.0-only and uses PyMuPDF under its AGPL
terms. See [third-party notices](../THIRD_PARTY_NOTICES.md) for individual
component terms.
