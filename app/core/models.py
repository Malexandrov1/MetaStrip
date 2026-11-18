"""Shared contracts for processing services and the desktop interface."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class FileFormat(StrEnum):
    JPEG = "JPEG"
    PNG = "PNG"
    TIFF = "TIFF"
    WEBP = "WebP"
    PDF = "PDF"
    MP4 = "MP4"
    MOV = "MOV"


class VerificationState(StrEnum):
    PASSED = "Passed configured checks"
    WARNINGS = "Passed with warnings"
    FAILED = "Failed"
    UNSUPPORTED = "Unsupported"
    NOT_VERIFIED = "Not fully verified"


@dataclass(frozen=True)
class MetadataField:
    name: str
    value: str
    category: str = "Other"
    sensitive: bool = True


@dataclass(frozen=True)
class InspectionResult:
    path: Path
    format: FileFormat
    fields: tuple[MetadataField, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationResult:
    state: VerificationState
    checks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    remaining_fields: tuple[str, ...] = ()
    removed_categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProcessingOptions:
    output_dir: Path
    suffix: str = "_clean"
    preserve_color_profile: bool = True
    remove_pdf_annotations: bool = False


@dataclass(frozen=True)
class ProcessingResult:
    source: Path
    output: Path | None = None
    format: FileFormat | None = None
    verification: VerificationResult = field(
        default_factory=lambda: VerificationResult(VerificationState.NOT_VERIFIED)
    )
    error: str | None = None
    cancelled: bool = False

    @property
    def status(self) -> str:
        if self.cancelled:
            return "Cancelled"
        if self.verification.state == VerificationState.UNSUPPORTED:
            return VerificationState.UNSUPPORTED.value
        if self.error:
            return VerificationState.FAILED.value
        return self.verification.state.value


class MetaStripError(Exception):
    """A safe, user-facing processing error."""


class UnsupportedFormatError(MetaStripError):
    """The file format cannot be safely processed."""


class DependencyError(MetaStripError):
    """A required local executable or library is unavailable."""


class CancelledError(MetaStripError):
    """Processing was cancelled before the output was committed."""
