"""Pass filenames to ExifTool using its Unicode-safe input on Windows."""

import os
import tempfile
from pathlib import Path
from threading import Event

from app.core.models import MetaStripError
from app.core.tools import check_cancel, run_tool


def run_exiftool(
    executable: str,
    options: list[str],
    path: Path,
    cancel: Event | None,
) -> bytes:
    args = [executable, "-config", "", *options]
    filename = str(path)
    if os.name != "nt":
        return run_tool([*args, filename], cancel)

    # Perl's Windows argv uses the active code page. The -@ reader accepts UTF-8
    # and passes one argument per line, so quoting and metacharacters stay literal.
    check_cancel(cancel)
    if "\n" in filename or "\r" in filename:
        raise MetaStripError("The filename contains unsupported line breaks.")
    with tempfile.TemporaryFile() as arguments:
        arguments.write(filename.encode("utf-8") + b"\n")
        arguments.seek(0)
        return run_tool([*args, "-charset", "filename=UTF8", "-@", "-"], cancel, stdin=arguments)
