"""Capture actual Qt-rendered pages with synthetic files and isolated preferences.

Run with QT_SCALE_FACTOR=1.5 for an additional high-DPI render. No user files or
preferences are read; screenshots are local QA artifacts, never mockups.
"""

import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.main_window import MainWindow  # noqa: E402


def load_qa_fonts() -> None:
    """Windows offscreen Qt has no automatic platform font database."""
    if QFontDatabase.families():
        return
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "segoeuib.ttf", "segoeuisl.ttf"):
        if (fonts / filename).is_file():
            QFontDatabase.addApplicationFont(str(fonts / filename))


def wait_idle(window: MainWindow, timeout_ms: int = 10000) -> None:
    def idle() -> bool:
        return not any(
            getattr(window, name, False)
            for name in ("_batch_active", "_inspection_active", "_diagnostics_active")
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
    if not idle():
        raise RuntimeError("Background work did not finish within the UI capture timeout.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/product-design"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    load_qa_fonts()
    with TemporaryDirectory(prefix="qa-", dir=args.output) as temporary:
        root = Path(temporary)
        window = MainWindow(settings_path=root / "settings.json")
        window.show()
        QApplication.processEvents()

        def capture(name: str, page: int) -> None:
            window.stack.setCurrentIndex(page)
            QTest.qWait(320)
            QApplication.processEvents()
            if not window.grab().save(str(args.output / f"{name}.png")):
                raise RuntimeError(f"Could not save screenshot {name}.")

        wait_idle(window)
        for index, name in enumerate(("clean-empty", "inspector-empty", "history-off", "settings")):
            capture(name, index)
        photo = root / "Field notes - waterfront and architecture.jpg"
        exif = Image.Exif()
        exif[271] = "Example Camera"
        exif[315] = "Sample Photographer"
        exif[305] = "Sample Editing Software"
        Image.new("RGB", (48, 32), (50, 85, 100)).save(photo, exif=exif)
        window.add_files([photo])
        capture("clean-queued", 0)
        window.output_edit.setText(str(root / "clean"))
        window.start_processing()
        wait_idle(window)
        window.queue.selectRow(0)
        capture("clean-result", 0)
        window.inspect_file(photo)
        wait_idle(window)
        capture("inspector-populated", 1)
        window.metadata_tree.setFocus(Qt.FocusReason.OtherFocusReason)
        capture("inspector-focused", 1)
        window.history_enabled.setChecked(True)
        window.save_preferences()
        capture("history-empty", 2)
        window.start_processing()
        wait_idle(window)
        capture("history-populated", 2)
        window.resize(960, 700)
        capture("clean-compact", 0)
        capture("settings-compact", 3)
        window.resize(1440, 960)
        capture("settings-large", 3)
        window.theme_combo.setCurrentText("Light")
        window.save_preferences()
        capture("settings-light", 3)
        wait_idle(window)
        window.close()
        QTest.qWait(100)
    print(f"Actual Qt renders saved to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
