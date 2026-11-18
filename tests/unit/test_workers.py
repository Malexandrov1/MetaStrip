"""Qt worker tests use fake processors to isolate queue behavior."""

from pathlib import Path
from threading import Event

import pytest

pytest.importorskip("PySide6")

from app.core.models import (  # noqa: E402
    ProcessingOptions,
    ProcessingResult,
    VerificationResult,
    VerificationState,
)
from app.workers import processing_worker  # noqa: E402


def test_batch_continues_after_file_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sources = [tmp_path / "broken.jpg", tmp_path / "good.png"]

    class FakeSanitizer:
        def process(
            self, path: Path, options: ProcessingOptions, cancel: Event | None = None
        ) -> ProcessingResult:
            if path == sources[0]:
                return ProcessingResult(path, error="Invalid file")
            return ProcessingResult(
                path,
                output=options.output_dir / path.name,
                verification=VerificationResult(VerificationState.PASSED),
            )

    monkeypatch.setattr("app.core.sanitizer.Sanitizer", FakeSanitizer)
    worker = processing_worker.BatchWorker(sources, ProcessingOptions(tmp_path / "out"))
    received: list[tuple[int, ProcessingResult]] = []
    summaries = []
    worker.result_ready.connect(lambda index, result: received.append((index, result)))
    worker.summary.connect(summaries.append)
    worker.run()
    assert len(received) == 2
    assert received[0][1].error
    assert received[1][1].error is None
    assert summaries == [{"passed": 1, "warnings": 0, "failed": 1, "cancelled": 0}]


def test_cancelled_batch_emits_terminal_results(tmp_path: Path) -> None:
    sources = [tmp_path / "one.jpg", tmp_path / "two.png"]
    worker = processing_worker.BatchWorker(sources, ProcessingOptions(tmp_path / "out"))
    received: list[ProcessingResult] = []
    worker.result_ready.connect(lambda _index, result: received.append(result))
    worker.cancel()
    worker.run()
    assert len(received) == 2
    assert all(result.cancelled for result in received)


def test_inspector_cancel_is_distinct_from_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.core.tools import check_cancel

    class FakeInspector:
        def inspect(self, path: Path, cancel=None):
            check_cancel(cancel)
            raise AssertionError("A cancelled inspection must stop before extracting metadata")

    monkeypatch.setattr("app.core.inspector.MetadataInspector", FakeInspector)
    worker = processing_worker.InspectorWorker(tmp_path / "photo.jpg")
    cancelled = []
    failed = []
    inspected = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.failed.connect(failed.append)
    worker.inspected.connect(inspected.append)
    worker.cancel()
    worker.run()
    assert cancelled == [True]
    assert failed == []
    assert inspected == []


@pytest.mark.gui
def test_main_window_queue_smoke(qtbot, tmp_path: Path, jpeg_file: Path) -> None:
    from app.ui.main_window import MainWindow

    window = MainWindow(settings_path=tmp_path / "settings.json")
    qtbot.addWidget(window)
    window.show()
    window.add_files([jpeg_file, jpeg_file])
    assert window.queue.rowCount() == 1
    assert window.files == [jpeg_file]
    window.close()
