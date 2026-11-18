"""Cancellation-aware batch and inspection workers without widget access."""

from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from app.core.models import ProcessingOptions, ProcessingResult, VerificationState


class BatchWorker(QThread):
    started_file = Signal(int, str)
    result_ready = Signal(int, object)
    progress = Signal(int, int)
    summary = Signal(object)

    def __init__(self, files: list[Path], options: ProcessingOptions) -> None:
        super().__init__()
        self.files = tuple(files)
        self.options = options
        self.cancel_event = Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        counts = {"passed": 0, "warnings": 0, "failed": 0, "cancelled": 0}
        try:
            from app.core.sanitizer import Sanitizer

            sanitizer = Sanitizer()
        except ImportError:
            for index, path in enumerate(self.files):
                self.result_ready.emit(
                    index,
                    ProcessingResult(
                        path,
                        error=(
                            "Processing dependencies are unavailable. Check Settings diagnostics."
                        ),
                    ),
                )
                self.progress.emit(index + 1, len(self.files))
            counts["failed"] = len(self.files)
            self.summary.emit(counts)
            return
        for index, path in enumerate(self.files):
            if self.cancel_event.is_set():
                result = ProcessingResult(path, cancelled=True)
            else:
                self.started_file.emit(index, str(path))
                try:
                    result = sanitizer.process(path, self.options, self.cancel_event)
                except Exception:
                    # Do not leak metadata, subprocess output, or tracebacks to logs.
                    result = ProcessingResult(path, error="Unexpected processing error.")
            if result.cancelled:
                counts["cancelled"] += 1
            elif result.error or result.verification.state in (
                VerificationState.FAILED,
                VerificationState.UNSUPPORTED,
                VerificationState.NOT_VERIFIED,
            ):
                counts["failed"] += 1
            elif result.verification.state == VerificationState.PASSED:
                counts["passed"] += 1
            else:
                counts["warnings"] += 1
            self.result_ready.emit(index, result)
            self.progress.emit(index + 1, len(self.files))
        self.summary.emit(counts)


class InspectorWorker(QThread):
    inspected = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.cancel_event = Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        from app.core.models import CancelledError, MetaStripError

        try:
            from app.core.inspector import MetadataInspector

            result = MetadataInspector().inspect(self.path, self.cancel_event)
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.inspected.emit(result)
        except CancelledError:
            self.cancelled.emit()
        except MetaStripError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("The file could not be inspected safely.")


class DependencyWorker(QThread):
    """Probe local versions outside the GUI thread; never install or download tools."""

    diagnosed = Signal(object)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.cancel_event = Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        from app.core.models import CancelledError

        try:
            from app.utils.dependency_checker import dependency_diagnostics

            result = dependency_diagnostics(self.cancel_event)
            if not self.cancel_event.is_set():
                self.diagnosed.emit(result)
        except CancelledError:
            pass
        except Exception:
            self.failed.emit("Local tool diagnostics could not be completed.")
