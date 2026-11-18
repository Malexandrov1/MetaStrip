"""Content-based identification; file extensions are not trusted."""

from pathlib import Path

from app.core.models import FileFormat, MetaStripError, UnsupportedFormatError

_MP4_BRANDS = {
    b"isom",
    b"iso2",
    b"iso3",
    b"iso4",
    b"iso5",
    b"iso6",
    b"iso7",
    b"iso8",
    b"iso9",
    b"mp41",
    b"mp42",
    b"avc1",
    b"M4V ",
    b"MSNV",
    b"dash",
}


def detect_format(path: Path) -> FileFormat:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise MetaStripError("Choose a regular file; symbolic links are not accepted.")
    try:
        with path.open("rb") as stream:
            header = stream.read(4096)
    except OSError as exc:
        raise MetaStripError("The input file cannot be read.") from exc
    if header.startswith(b"\xff\xd8\xff"):
        return FileFormat.JPEG
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileFormat.PNG
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return FileFormat.TIFF
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return FileFormat.WEBP
    if header.startswith(b"%PDF-"):
        return FileFormat.PDF
    if header[4:8] == b"ftyp" and len(header) >= 16:
        brand = header[8:12]
        if brand == b"qt  ":
            return FileFormat.MOV
        if brand in _MP4_BRANDS:
            return FileFormat.MP4
    raise UnsupportedFormatError("Unsupported or unrecognized file contents.")
