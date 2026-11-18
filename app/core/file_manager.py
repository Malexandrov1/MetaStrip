"""Transactional outputs with atomic no-overwrite publication."""

import hashlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event

from app.core.models import MetaStripError
from app.core.tools import check_cancel


def file_digest(path: Path, cancel: Event | None = None) -> str:
    digest = hashlib.sha256()
    check_cancel(cancel)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            check_cancel(cancel)
            digest.update(block)
    check_cancel(cancel)
    return digest.hexdigest()


def validate_suffix(suffix: str) -> None:
    if not suffix or len(suffix) > 64 or any(c in suffix for c in '<>:"/\\|?*\x00'):
        raise MetaStripError("Filename suffix must be 1–64 characters without path separators.")
    if any(ord(char) < 32 for char in suffix) or suffix.endswith((" ", ".")):
        raise MetaStripError("The filename suffix contains unsupported characters.")


@contextmanager
def temporary_output(directory: Path, extension: str) -> Iterator[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".metastrip-", suffix=extension, dir=directory)
    os.close(descriptor)
    path = Path(name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def publish_output(temporary: Path, source: Path, directory: Path, suffix: str) -> Path:
    """Publish a verified file atomically without replacing an existing destination.

    Windows rename refuses an existing destination and also works on FAT/exFAT.
    POSIX rename can overwrite, so those systems use an exclusive hard link.
    """
    validate_suffix(suffix)
    limit = 255 if os.name == "nt" else os.pathconf(directory, "PC_NAME_MAX")

    def name_length(value: str) -> int:
        if os.name == "nt":
            return len(value.encode("utf-16-le")) // 2
        return len(os.fsencode(value))

    for number in range(10000):
        extra = "" if number == 0 else f" ({number})"
        ending = f"{suffix}{extra}{source.suffix}"
        stem = source.stem
        while limit > 0 and stem and name_length(stem + ending) > limit:
            stem = stem[:-1]
        if not stem:
            raise MetaStripError("Use a shorter suffix for the selected output filesystem.")
        target = directory / (stem + ending)
        try:
            if os.name == "nt":
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
            return target
        except FileExistsError:
            continue
        except OSError as exc:
            raise MetaStripError(
                "The sanitized copy could not be safely published. Check folder permissions "
                "and free space. On macOS/Linux, choose a filesystem supporting hard links."
            ) from exc
    raise MetaStripError("Too many filename collisions in the selected output directory.")
