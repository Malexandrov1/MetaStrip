"""Exercise the actual application entry point in an isolated native Qt session.

This is a bounded stability check, not an executable build or visual design test.
It uses synthetic input and a temporary preference store, never the user's files.
"""

import argparse
import os
import sys
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app.ui.main_window as window_module  # noqa: E402
from app.main import main as launch_application  # noqa: E402
from app.ui.motion import set_reduced_motion  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("windows", "offscreen"), default="offscreen")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = args.platform
    original_window = window_module.MainWindow
    failures: list[str] = []
    with TemporaryDirectory(prefix="metastrip-stability-") as temporary:
        root = Path(temporary)
        source = root / "synthetic.jpg"
        exif = Image.Exif()
        exif[315] = "Synthetic author"
        Image.new("RGB", (24, 16), (30, 90, 120)).save(source, exif=exif)
        source_bytes = source.read_bytes()

        class StabilityWindow(original_window):
            def __init__(self) -> None:
                super().__init__(settings_path=root / "settings.json")
                self._stability_step = 0
                self._stability_ticks = 0
                self._stability_timer = QTimer(self)
                self._stability_timer.timeout.connect(self._exercise)
                self._stability_timer.start(50)

            def _exercise(self) -> None:
                self._stability_ticks += 1
                try:
                    if self._stability_ticks > 240:
                        raise TimeoutError("Application stability check exceeded 12 seconds.")
                    if self._stability_step < 30:
                        self.stack.setCurrentIndex(self._stability_step % 4)
                        self.preserve_icc.setChecked(self._stability_step % 2 == 0)
                        self.pdf_annotations.setChecked(self._stability_step % 3 == 0)
                        set_reduced_motion(self._stability_step % 5 == 0)
                        self.start_button.set_busy(self._stability_step % 2 == 0)
                        self.start_button.grab()
                        if self._stability_step % 7 == 0:
                            self.save_preferences_button.confirm("Checked")
                            self.resize(980, 720)
                        else:
                            self.resize(1180, 820)
                        self._stability_step += 1
                    elif self._stability_step == 30:
                        self.add_files([source])
                        self.output_edit.setText(str(root / "clean"))
                        self.start_processing()
                        self._stability_step = 31
                    elif self._stability_step == 31 and not self._batch_active:
                        result = self.results[0]
                        assert result.output is not None and not result.error, result.error
                        with Image.open(source) as first, Image.open(result.output) as second:
                            assert first.tobytes() == second.tobytes()
                            assert not second.getexif().get(315)
                        assert source.read_bytes() == source_bytes
                        self.inspect_file(source)
                        self._stability_step = 32
                    elif self._stability_step == 32 and not self._inspection_active:
                        assert self.metadata_tree.topLevelItemCount() > 0
                        self.stack.setCurrentIndex(3)
                        self.start_processing()
                        self.cancel_processing()
                        self._stability_step = 33
                    elif self._stability_step == 33 and not self._batch_active:
                        assert self.results[0].cancelled
                        assert source.read_bytes() == source_bytes
                        if self._diagnostics_active:
                            return
                        self._stability_timer.stop()
                        if args.screenshot:
                            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                            assert self.grab().save(str(args.screenshot))
                        print(
                            "PASS: native window, 30 navigation/motion cycles, settings controls, "
                            "JPEG cleanup, inspection, cancellation and graceful close.",
                            flush=True,
                        )
                        self.close()
                except Exception:
                    failures.append(traceback.format_exc())
                    print(failures[-1], file=sys.stderr, flush=True)
                    self._stability_timer.stop()
                    self.cancel_processing()
                    self.cancel_inspection()
                    if self.dependency_worker:
                        self.dependency_worker.cancel()
                    self.close()
                    QTimer.singleShot(1000, lambda: QApplication.instance().exit(1))

        window_module.MainWindow = StabilityWindow
        try:
            status = launch_application()
        finally:
            window_module.MainWindow = original_window
    return 1 if failures else status


if __name__ == "__main__":
    raise SystemExit(main())
