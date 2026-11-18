"""Bounded local subprocess execution with cooperative cancellation."""

import os
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from threading import Event
from typing import BinaryIO

from app.core.models import CancelledError, DependencyError, MetaStripError


def video_input_args(path: Path) -> list[str]:
    """Read only the selected local MP4/MOV container, without external tracks."""
    return [
        "-protocol_whitelist",
        "file,pipe",
        "-f",
        "mov",
        "-enable_drefs",
        "0",
        "-use_absolute_path",
        "0",
        "-i",
        str(path.resolve()),
    ]


def check_cancel(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise CancelledError("Processing cancelled; no output was committed.")


def run_tool(
    args: list[str],
    cancel: Event | None = None,
    timeout: float = 120,
    *,
    stdin: BinaryIO | None = None,
) -> bytes:
    check_cancel(cancel)
    # Spool output to avoid unbounded in-memory PIPE buffers from malicious files.
    with tempfile.TemporaryFile() as captured:
        job = None
        if os.name == "nt":
            from app.core.windows_job import WindowsJob

            try:
                job = WindowsJob()
            except OSError as exc:
                raise DependencyError(
                    "Windows could not isolate the local tool process tree."
                ) from exc
        try:
            process = subprocess.Popen(
                args,
                stdin=stdin if stdin is not None else subprocess.DEVNULL,
                stdout=captured,
                stderr=subprocess.DEVNULL,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) | 0x00000004)
                if os.name == "nt"
                else 0,
                start_new_session=os.name != "nt",
            )
        except OSError as exc:
            if job:
                job.close()
            raise DependencyError("The required local executable cannot be started.") from exc
        started = time.monotonic()
        try:
            if job:
                try:
                    job.assign_and_resume(process.pid)
                except OSError as exc:
                    raise DependencyError(
                        "Windows could not isolate and resume the local tool process tree."
                    ) from exc
            while True:
                check_cancel(cancel)
                if time.monotonic() - started > timeout:
                    raise MetaStripError("The local tool exceeded its processing timeout.")
                if os.fstat(captured.fileno()).st_size > 32 * 1024 * 1024:
                    raise MetaStripError("Metadata extraction exceeded the supported size limit.")
                try:
                    process.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise MetaStripError("The local tool rejected this file or processing operation.")
            captured.seek(0)
            output = captured.read(32 * 1024 * 1024 + 1)
            if len(output) > 32 * 1024 * 1024:
                raise MetaStripError("Metadata extraction exceeded the supported size limit.")
            return output
        finally:
            if job:
                job.close()
            else:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            if process.poll() is None:
                process.kill()
                process.wait()
