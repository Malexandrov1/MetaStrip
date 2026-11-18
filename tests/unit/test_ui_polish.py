"""Product controls, privacy choices and UI state synchronization regressions."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QMimeData, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton

from app.core.models import (
    InspectionResult,
    MetadataField,
    ProcessingResult,
    VerificationResult,
    VerificationState,
)
from app.ui.main_window import MainWindow
from app.utils.preferences import HistoryStore, PreferenceStore


def wait_for_idle(instance: MainWindow, timeout_ms: int = 10000) -> None:
    """Use Qt's real event loop so PySide workers can acquire the Python GIL."""

    def idle() -> bool:
        return not any(
            getattr(instance, flag, False)
            for flag in ("_batch_active", "_inspection_active", "_diagnostics_active")
        )

    if idle():
        return
    loop = QEventLoop()
    poll = QTimer(loop)
    deadline = QTimer(loop)
    deadline.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if idle() else None)
    deadline.timeout.connect(loop.quit)
    poll.start(10)
    deadline.start(timeout_ms)
    loop.exec()
    poll.stop()
    deadline.stop()
    assert idle(), "Background workers failed to finish within the deadline."


@pytest.fixture
def window(qtbot, tmp_path: Path):
    instance = MainWindow(settings_path=tmp_path / "settings.json")
    # pytest-qt deletes registered widgets before fixture teardown. Drain workers
    # in its pre-close callback, rather than accessing an already deleted window.
    qtbot.addWidget(instance, before_close_func=wait_for_idle)
    instance.show()
    QApplication.processEvents()
    wait_for_idle(instance)
    return instance


@pytest.mark.gui
def test_sidebar_license_notice_supports_keyboard_and_official_link(window, qtbot, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)

    window.stack.setCurrentIndex(1)
    assert window.licenses_button.isVisible()
    window.licenses_button.setFocus()
    qtbot.keyClick(window.licenses_button, Qt.Key.Key_Space)
    dialog = window.findChild(QMessageBox, "LicensesDialog")
    assert dialog is not None
    qtbot.waitUntil(dialog.isVisible)
    assert "Copyright (c) 2026 MetaStrip contributors" in dialog.text()
    assert "without warranty" in dialog.informativeText()
    assert "redistribute" in dialog.informativeText()
    assert "version 3 only" in dialog.informativeText()
    assert not opened

    link = next(button for button in dialog.buttons() if button.text() == "Read AGPLv3")
    link.setFocus()
    qtbot.keyClick(link, Qt.Key.Key_Space)
    assert opened == [QUrl("https://www.gnu.org/licenses/agpl-3.0.html")]
    if (dialog := window.findChild(QMessageBox, "LicensesDialog")) is not None:
        dialog.close()


@pytest.mark.gui
@pytest.mark.parametrize("name", ["preserve_icc", "pdf_annotations", "history_enabled"])
def test_settings_checkboxes_support_mouse_space_focus_and_disabled(window, qtbot, name) -> None:
    window.stack.setCurrentIndex(3)
    checkbox = getattr(window, name)
    checkbox.ensurePolished()
    initial = checkbox.isChecked()
    qtbot.mouseClick(checkbox, Qt.MouseButton.LeftButton)
    assert checkbox.isChecked() != initial
    checkbox.setFocus()
    qtbot.keyClick(checkbox, Qt.Key.Key_Space)
    assert checkbox.isChecked() == initial
    checkbox.setEnabled(False)
    qtbot.keyClick(checkbox, Qt.Key.Key_Space)
    assert checkbox.isChecked() == initial


@pytest.mark.gui
def test_history_requires_explicit_action_and_has_both_empty_states(window, qtbot) -> None:
    window.stack.setCurrentIndex(2)
    assert not window.preferences.history_enabled
    assert window.history_empty_title.text() == "Processing history is off"
    assert not window.history_store.path.exists()
    window.suffix_edit.setText("_unsaved")
    qtbot.mouseClick(window.history_enable_button, Qt.MouseButton.LeftButton)
    assert window.preferences.history_enabled
    assert PreferenceStore(window.preferences_store.path).load().history_enabled
    assert window.preferences.suffix == "_clean"
    assert window.history_empty_title.text() == "Nothing here yet"


@pytest.mark.gui
def test_browse_drop_and_batch_use_one_canonical_queue_entry(
    window,
    qtbot,
    monkeypatch,
    tmp_path: Path,
    jpeg_file: Path,
) -> None:
    folder = tmp_path / "alias"
    folder.mkdir()
    source = jpeg_file.with_name("фото & 日本 " + "x" * 95 + ".jpe")
    source.write_bytes(jpeg_file.read_bytes())
    destination = tmp_path / "out"
    alias = str(folder / ".." / source.name)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_: ([alias], ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: str(destination))
    browse = window.drop_zone.findChild(QPushButton)
    qtbot.mouseClick(browse, Qt.MouseButton.LeftButton)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source)), QUrl("https://example.invalid/photo.jpe")])
    enter = QDragEnterEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    drop = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(window.drop_zone, enter)
    assert enter.isAccepted()
    QApplication.sendEvent(window.drop_zone, drop)
    assert drop.isAccepted()
    assert window.queue.rowCount() == 1 and window.files == [source]
    assert window.queue.item(0, 0).text() == source.name

    qtbot.mouseClick(window.output_browse, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    window.start_processing()  # A second request while the worker is active is ignored.
    wait_for_idle(window)
    assert len(list(destination.iterdir())) == 1
    assert window.progress.value() == window.progress.maximum() == 1
    assert window.results[0].output is not None
    qtbot.mouseClick(window.result_toggle, Qt.MouseButton.LeftButton)
    assert source.name in window.details.text() and window.details_scroll.isVisible()
    qtbot.mouseClick(window.clear_button, Qt.MouseButton.LeftButton)
    assert window.queue.rowCount() == 0 and not window.start_button.isEnabled()


@pytest.mark.gui
def test_saving_appearance_keeps_current_folder_and_open_failure_is_visible(
    window,
    qtbot,
    monkeypatch,
    tmp_path: Path,
) -> None:
    window.output_edit.setText(str(tmp_path))
    qtbot.mouseClick(window.navigation.button(3), Qt.MouseButton.LeftButton)
    window.theme_combo.setCurrentText("Light")
    qtbot.mouseClick(window.save_preferences_button, Qt.MouseButton.LeftButton)
    assert window.preferences.theme == "Light"
    assert window.output_edit.text() == str(tmp_path)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or False)
    qtbot.mouseClick(window.navigation.button(0), Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.open_output_button, Qt.MouseButton.LeftButton)
    assert opened == [QUrl.fromLocalFile(str(tmp_path))]
    assert "could not be opened" in window.statusBar().currentMessage()


@pytest.mark.gui
def test_unreadable_settings_do_not_purge_history(qtbot, tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{invalid", encoding="utf-8")
    history = tmp_path / "history.json"
    history.write_text('[{"filename":"existing.jpg"}]', encoding="utf-8")
    window = MainWindow(settings_path=settings)
    qtbot.addWidget(window, before_close_func=wait_for_idle)
    window.stack.setCurrentIndex(2)
    assert history.read_text(encoding="utf-8") == '[{"filename":"existing.jpg"}]'


@pytest.mark.gui
def test_visible_history_updates_when_batch_finishes(
    window,
    qtbot,
    jpeg_file: Path,
    tmp_path: Path,
) -> None:
    window.enable_history()
    window.add_files([jpeg_file])
    window.output_edit.setText(str(tmp_path / "out"))
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(window.navigation.button(2), Qt.MouseButton.LeftButton)
    wait_for_idle(window)
    assert window.history_table.rowCount() == 1 and window.history_table.isVisible()
    assert window.history_table.item(0, 0).text() == jpeg_file.name
    assert len(window.history_table.item(0, 1).text()) == 19
    window.history_filter.setText("no-match")
    assert window.history_table.isRowHidden(0)
    window.history_filter.setText(jpeg_file.name.upper())
    assert not window.history_table.isRowHidden(0)


@pytest.mark.gui
def test_retention_options_and_explicit_settings_save(window) -> None:
    window.stack.setCurrentIndex(3)
    assert not window.retention_combo.isEnabled()
    assert [window.retention_combo.itemData(i) for i in range(window.retention_combo.count())] == [
        1,
        7,
        30,
        90,
        0,
    ]
    window.history_enabled.setChecked(True)
    assert window.retention_combo.isEnabled()
    window.retention_combo.setCurrentIndex(window.retention_combo.findData(0))
    window.suffix_edit.setText("_private")
    window.preserve_icc.setChecked(False)
    window.pdf_annotations.setChecked(True)
    assert window.preferences.suffix == "_clean"
    window.save_preferences()
    saved = window.preferences_store.load()
    assert saved.history_enabled and saved.history_retention_days == 0
    assert saved.suffix == "_private"
    assert not saved.preserve_color_profile and saved.remove_pdf_annotations


def test_never_retention_preserves_old_history_and_sorts_newest_first(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    now = datetime.now(UTC)
    records = [
        {"date": (now - timedelta(days=1000)).isoformat(), "filename": "old.jpg"},
        {"date": (now - timedelta(days=1)).isoformat(), "filename": "new.jpg"},
    ]
    path.write_text(json.dumps(records), encoding="utf-8")
    store = HistoryStore(path)
    store.prune(0)
    assert [entry["filename"] for entry in store.entries(0)] == ["new.jpg", "old.jpg"]
    store.prune(30)
    assert [entry["filename"] for entry in store.entries(0)] == ["new.jpg"]


@pytest.mark.gui
def test_disabling_history_purges_records_and_clear_history_works(window) -> None:
    window.history_enabled.setChecked(True)
    window.save_preferences()
    window.history_store.append(ProcessingResult(Path("example.jpg")))
    window._load_history()
    assert window.history_table.rowCount() == 1
    window.clear_history()
    assert not window.history_store.path.exists()
    window.history_store.append(ProcessingResult(Path("example.jpg")))
    window.history_enabled.setChecked(False)
    window.save_preferences()
    assert not window.history_store.path.exists()
    assert window.history_table.rowCount() == 0
    assert not window.preferences.history_enabled


@pytest.mark.gui
def test_incomplete_verification_retains_honest_status(window, jpeg_file: Path) -> None:
    window.add_files([jpeg_file])
    result = ProcessingResult(
        jpeg_file,
        verification=VerificationResult(
            VerificationState.NOT_VERIFIED, warnings=("Independent checks unavailable.",)
        ),
    )
    window._file_finished(0, result)
    assert "Not fully verified" in window.queue.item(0, 3).text()
    assert "Independent checks unavailable" in window.queue.item(0, 3).toolTip()


@pytest.mark.gui
def test_rapid_navigation_preserves_page_input_and_finishes_on_latest_page(window, qtbot) -> None:
    window.suffix_edit.setText("_draft")
    for page in (1, 3, 0, 2, 3, 0, 1, 3):
        window.stack.setCurrentIndex(page)
        QTest.qWait(10)
    qtbot.wait(350)
    assert window.stack.currentIndex() == 3
    assert window.suffix_edit.text() == "_draft"
    assert window.stack.currentWidget().isVisible()


@pytest.mark.gui
def test_copy_metadata_value_does_not_execute_or_interpret_content(window, qtbot) -> None:
    from PySide6.QtWidgets import QApplication

    from app.core.models import FileFormat

    text = "<script>private</script> & $(echo example)"
    window._inspection_ready(
        InspectionResult(
            Path("synthetic.jpg"),
            FileFormat.JPEG,
            fields=(MetadataField("EXIF:Artist", text, "Author"),),
        )
    )
    tree = window.metadata_tree
    target = None
    for i in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(i)
        if group.childCount():
            target = group.child(0)
            break
    assert target is not None
    tree.setCurrentItem(target)
    window.stack.setCurrentIndex(1)
    qtbot.mouseClick(window.copy_value_button, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == text


@pytest.mark.gui
def test_queue_removal_keeps_remaining_results_correctly_indexed(window, tmp_path: Path) -> None:
    sources = [tmp_path / f"photo-{number}.jpg" for number in range(3)]
    for source in sources:
        source.write_bytes(b"fixture placeholder; queue does not decode files")
    window.add_files(sources)
    for row, source in enumerate(sources):
        window._file_finished(
            row,
            ProcessingResult(
                source,
                verification=VerificationResult(
                    VerificationState.WARNINGS, warnings=("Limited coverage.",)
                ),
            ),
        )
    window.queue.selectRow(1)
    window.remove_selected()
    assert window.files == [sources[0], sources[2]]
    assert window.results[0].source == sources[0]
    assert window.results[1].source == sources[2]
    window.queue.clearSelection()
    window.remove_selected()
    assert len(window.results) == 2


@pytest.mark.gui
def test_processing_cancellation_recovers_controls_and_preserves_original(
    window, qtbot, jpeg_file: Path, tmp_path: Path
) -> None:
    original = jpeg_file.read_bytes()
    window.add_files([jpeg_file])
    destination = tmp_path / "clean"
    window.output_edit.setText(str(destination))
    window.start_processing()
    assert window._batch_active
    assert not window.start_button.isEnabled()
    window.cancel_processing()
    wait_for_idle(window)
    assert window.start_button.isEnabled()
    assert not window.cancel_button.isEnabled()
    assert jpeg_file.read_bytes() == original
    assert window.results[0].cancelled
    assert not destination.exists() or not list(destination.iterdir())


@pytest.mark.gui
def test_immediate_close_prevents_deferred_diagnostics_start(qtbot, tmp_path: Path) -> None:
    instance = MainWindow(settings_path=tmp_path / "settings.json")
    qtbot.addWidget(instance)
    instance.close()
    QApplication.processEvents()
    assert instance._closing
    assert not instance._diagnostics_active
    assert instance.dependency_worker is None


@pytest.mark.gui
def test_close_waits_for_active_diagnostics_before_widget_destruction(
    window, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    from PySide6.QtCore import QThread

    class WaitingDependencyWorker(QThread):
        def __init__(self) -> None:
            super().__init__()
            self.cancel_event = Event()

        def run(self) -> None:
            self.cancel_event.wait(timeout=5)

        def cancel(self) -> None:
            self.cancel_event.set()

    # Use the actual existing signal declarations and replace only the bounded
    # worker body, so the production queued completion path is exercised.
    monkeypatch.setattr(
        "app.workers.processing_worker.DependencyWorker.run", WaitingDependencyWorker.run
    )
    window.refresh_diagnostics()
    assert window._diagnostics_active
    worker = window.dependency_worker
    window.close()
    wait_for_idle(window)
    assert worker.cancel_event.is_set()
    assert not worker.isRunning()
    assert not window.isVisible()
