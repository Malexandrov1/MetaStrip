"""Run native image safety checks when the full pytest stack is unavailable.

This is a limited standard-library unittest runner, not a replacement for pytest,
Qt tests, independent ExifTool inspection, PDF tests or video integration tests.
Requires Pillow, which is also a regular application dependency.
"""

import hashlib
import os
import signal
import stat
import struct
import sys
import time
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread, Timer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageCms, PngImagePlugin  # noqa: E402

from app.core.file_manager import file_digest  # noqa: E402
from app.core.formats import detect_format  # noqa: E402
from app.core.inspector import MetadataInspector  # noqa: E402
from app.core.models import (  # noqa: E402
    CancelledError,
    FileFormat,
    MetaStripError,
    ProcessingOptions,
    VerificationResult,
    VerificationState,
)
from app.core.sanitizer import Sanitizer  # noqa: E402
from app.core.tools import run_tool  # noqa: E402


class NativeImageSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory(prefix="metastrip-offline-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.output = self.root / "clean"
        self.jpeg = self.root / "private.jpg"
        self.png = self.root / "private.png"
        exif = Image.Exif()
        exif[271] = "Private Camera"
        exif[315] = "Private Author"
        Image.new("RGB", (20, 14), (20, 80, 160)).save(self.jpeg, exif=exif)
        info = PngImagePlugin.PngInfo()
        info.add_text("Author", "Private PNG Author")
        info.add_itxt("Description", "Private Unicode Description")
        info.add_text("Software", "Private Software", zip=True)
        Image.new("RGBA", (20, 14), (10, 100, 190, 80)).save(self.png, pnginfo=info)

    def test_detection_uses_content(self) -> None:
        renamed = self.root / "renamed.pdf"
        renamed.write_bytes(self.jpeg.read_bytes())
        self.assertEqual(detect_format(renamed), FileFormat.JPEG)
        self.assertEqual(detect_format(self.png), FileFormat.PNG)

    def test_streaming_hash_honors_inflight_cancellation(self) -> None:
        cancel = Event()
        original = self.jpeg.read_bytes()

        def read_then_cancel(_size: int) -> bytes:
            cancel.set()
            return b"block"

        with patch.object(Path, "open") as mocked_open:
            mocked_open.return_value.__enter__.return_value.read.side_effect = read_then_cancel
            with self.assertRaises(CancelledError):
                file_digest(self.jpeg, cancel)
        self.assertEqual(self.jpeg.read_bytes(), original)

    def test_jpeg_extraction(self) -> None:
        values = [field.value for field in MetadataInspector().inspect(self.jpeg).fields]
        self.assertTrue(any("Private Author" in value for value in values))

    def test_png_extraction(self) -> None:
        values = [field.value for field in MetadataInspector().inspect(self.png).fields]
        self.assertTrue(any("Private PNG Author" in value for value in values))

    def _check_image(self, source: Path) -> None:
        original = source.read_bytes()
        result = Sanitizer().process(source, ProcessingOptions(self.output))
        self.assertIsNone(result.error, result.error)
        self.assertIsNotNone(result.output)
        self.assertEqual(source.read_bytes(), original)
        self.assertNotEqual(result.output, source)
        self.assertNotEqual(result.verification.state, VerificationState.FAILED)
        with Image.open(source) as before, Image.open(result.output) as after:
            self.assertEqual(before.convert("RGBA").tobytes(), after.convert("RGBA").tobytes())
        values = [field.value for field in MetadataInspector().inspect(result.output).fields]
        self.assertFalse(any("Private" in value for value in values))

    def test_jpeg_cleanup_preserves_pixels_and_original(self) -> None:
        self._check_image(self.jpeg)

    def test_png_cleanup_preserves_pixels_and_original(self) -> None:
        self._check_image(self.png)

    def test_collision_preserves_existing_output(self) -> None:
        options = ProcessingOptions(self.output)
        first = Sanitizer().process(self.jpeg, options)
        self.assertIsNone(first.error, first.error)
        self.assertIsNotNone(first.output)
        digest = hashlib.sha256(first.output.read_bytes()).digest()
        second = Sanitizer().process(self.jpeg, options)
        self.assertIsNone(second.error, second.error)
        self.assertIsNotNone(second.output)
        self.assertNotEqual(first.output, second.output)
        self.assertEqual(hashlib.sha256(first.output.read_bytes()).digest(), digest)

    def test_cancellation_leaves_no_outputs(self) -> None:
        cancel = Event()
        cancel.set()
        result = Sanitizer().process(self.jpeg, ProcessingOptions(self.output), cancel)
        self.assertTrue(result.cancelled)
        self.assertIsNone(result.output)
        self.assertTrue(not self.output.exists() or not list(self.output.iterdir()))

    def test_invalid_file_has_no_output(self) -> None:
        invalid = self.root / "invalid.jpg"
        invalid.write_bytes(b"not an image")
        result = Sanitizer().process(invalid, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIsNone(result.output)
        self.assertTrue(not self.output.exists() or not list(self.output.iterdir()))

    def test_failed_verification_discards_temporary_copy(self) -> None:
        failed = VerificationResult(VerificationState.FAILED, remaining_fields=("EXIF:Artist",))
        with patch("app.core.sanitizer.Verifier.verify", return_value=failed):
            result = Sanitizer().process(self.jpeg, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIsNone(result.output)
        self.assertFalse(list(self.output.iterdir()))

    def test_cancellation_during_processing_discards_temporary_copy(self) -> None:
        from app.core.image_cleaner import clean_image

        cancel = Event()

        def clean_then_cancel(*args) -> None:
            clean_image(*args)
            cancel.set()

        with patch("app.core.sanitizer.clean_image", side_effect=clean_then_cancel):
            result = Sanitizer().process(self.jpeg, ProcessingOptions(self.output), cancel)
        self.assertTrue(result.cancelled)
        self.assertIsNone(result.output)
        self.assertFalse(list(self.output.iterdir()))

    def test_jpeg_orientation_is_preserved(self) -> None:
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "Private Oriented Author"
        Image.new("RGB", (20, 14), (30, 90, 160)).save(self.jpeg, exif=exif)
        self._check_image(self.jpeg)
        result = Sanitizer().process(self.jpeg, ProcessingOptions(self.output))
        self.assertIsNotNone(result.output, result.error)
        with Image.open(result.output) as cleaned:
            self.assertEqual(cleaned.getexif().get(274), 6)
            self.assertNotIn(315, cleaned.getexif())

    def test_webp_cleanup_preserves_pixels(self) -> None:
        source = self.root / "private.webp"
        exif = Image.Exif()
        exif[315] = "Private WebP Author"
        Image.new("RGBA", (20, 14), (10, 120, 200, 50)).save(source, exif=exif, lossless=True)
        self._check_image(source)

    def test_png_bad_crc_is_refused(self) -> None:
        data = bytearray(self.png.read_bytes())
        marker = data.index(b"tEXt")
        data[marker + 4] ^= 1
        self.png.write_bytes(data)
        result = Sanitizer().process(self.png, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIsNone(result.output)

    def test_concurrent_collisions_are_safe(self) -> None:
        options = ProcessingOptions(self.output)
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(
                executor.map(lambda _: Sanitizer().process(self.jpeg, options), range(3))
            )
        self.assertTrue(
            all(result.error is None for result in results), [result.error for result in results]
        )
        self.assertEqual(len({result.output for result in results}), 3)
        self.assertEqual(len(list(self.output.iterdir())), 3)

    def test_tiff_without_exiftool_is_refused(self) -> None:
        source = self.root / "private.tif"
        Image.new("RGB", (12, 8)).save(source)
        original = source.read_bytes()
        with patch("app.utils.dependency_checker.shutil.which", return_value=None):
            result = Sanitizer().process(source, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIn("exiftool", result.error.lower())
        self.assertIsNone(result.output)
        self.assertEqual(source.read_bytes(), original)

    def test_suffix_cannot_escape_output_directory(self) -> None:
        result = Sanitizer().process(self.jpeg, ProcessingOptions(self.output, suffix="../escape"))
        self.assertTrue(result.error)
        self.assertIsNone(result.output)
        self.assertFalse((self.root / "escape.jpg").exists())

    def test_progressive_jpeg_removes_between_scan_comments_and_trailer(self) -> None:
        exif = Image.Exif()
        exif[315] = "Private Progressive Author"
        Image.effect_noise((40, 30), 60).convert("RGB").save(self.jpeg, progressive=True, exif=exif)
        original = self.jpeg.read_bytes()
        first_scan = original.index(b"\xff\xda")
        second_scan = original.index(b"\xff\xda", first_scan + 2)
        comment = b"Private Between Scan Comment"
        segment = b"\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment
        self.jpeg.write_bytes(
            original[:second_scan] + segment + original[second_scan:] + b"Private Appended Payload"
        )
        self._check_image(self.jpeg)
        result = Sanitizer().process(self.jpeg, ProcessingOptions(self.output))
        self.assertIsNone(result.error, result.error)
        self.assertNotIn(b"Private", result.output.read_bytes())
        with Image.open(result.output) as cleaned:
            self.assertTrue(cleaned.info.get("progressive"))

    def test_icc_policy_for_each_native_image_format(self) -> None:
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        for extension in ("jpg", "png", "webp"):
            source = self.root / f"profile.{extension}"
            Image.new("RGB", (20, 14), (30, 80, 150)).save(source, icc_profile=profile)
            original = source.read_bytes()
            for preserve in (True, False):
                with self.subTest(extension=extension, preserve=preserve):
                    options = ProcessingOptions(self.output, preserve_color_profile=preserve)
                    result = Sanitizer().process(source, options)
                    self.assertIsNone(result.error, result.error)
                    self.assertEqual(source.read_bytes(), original)
                    with Image.open(source) as before, Image.open(result.output) as after:
                        self.assertEqual(
                            before.convert("RGBA").tobytes(), after.convert("RGBA").tobytes()
                        )
                        self.assertEqual(
                            after.info.get("icc_profile"), profile if preserve else None
                        )

    def test_png_unknown_ancillary_chunk_is_removed(self) -> None:
        payload = b"Private Ancillary Payload"
        kind = b"vpAg"
        chunk = struct.pack(">I", len(payload)) + kind + payload
        chunk += struct.pack(">I", zlib.crc32(kind + payload))
        original = self.png.read_bytes()
        self.png.write_bytes(original[:33] + chunk + original[33:])
        result = Sanitizer().process(self.png, ProcessingOptions(self.output))
        self.assertIsNone(result.error, result.error)
        self.assertNotIn(payload, result.output.read_bytes())

    def test_png_unknown_critical_chunk_is_refused(self) -> None:
        payload = b"Private Critical Payload"
        kind = b"VPAG"
        chunk = struct.pack(">I", len(payload)) + kind + payload
        chunk += struct.pack(">I", zlib.crc32(kind + payload))
        original = self.png.read_bytes()
        self.png.write_bytes(original[:33] + chunk + original[33:])
        result = Sanitizer().process(self.png, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIsNone(result.output)
        self.assertFalse(self.output.exists() and list(self.output.iterdir()))

    def test_apng_is_refused(self) -> None:
        first = Image.new("RGBA", (20, 14), "blue")
        second = Image.new("RGBA", (20, 14), "red")
        first.save(self.png, save_all=True, append_images=[second], duration=100, loop=0)
        result = Sanitizer().process(self.png, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIsNone(result.output)

    def test_palette_png_transparency_is_preserved(self) -> None:
        image = Image.new("P", (20, 14), 0)
        image.putpalette([10, 20, 30, 180, 190, 200] + [0] * 762)
        image.putpixel((2, 2), 1)
        image.save(self.png, transparency=0)
        self._check_image(self.png)

    def test_extension_mismatch_is_refused(self) -> None:
        disguised = self.root / "disguised.png"
        disguised.write_bytes(self.jpeg.read_bytes())
        result = Sanitizer().process(disguised, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIn("extension", result.error.lower())
        self.assertIsNone(result.output)

    def test_output_publication_failure_cleans_temporary_copy(self) -> None:
        original = self.jpeg.read_bytes()
        with (
            patch("app.core.file_manager.os.link", side_effect=PermissionError("read only")),
            patch("app.core.file_manager.os.rename", side_effect=PermissionError("read only")),
        ):
            result = Sanitizer().process(self.jpeg, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIsNone(result.output)
        self.assertEqual(self.jpeg.read_bytes(), original)
        self.assertFalse(list(self.output.iterdir()))

    def test_output_directory_cannot_be_an_existing_file(self) -> None:
        self.output.write_bytes(b"Existing output file")
        result = Sanitizer().process(self.jpeg, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIsNone(result.output)
        self.assertEqual(self.output.read_bytes(), b"Existing output file")

    def test_readonly_source_is_preserved(self) -> None:
        original = self.jpeg.read_bytes()
        previous_mode = self.jpeg.stat().st_mode
        try:
            os.chmod(self.jpeg, stat.S_IREAD)
            result = Sanitizer().process(self.jpeg, ProcessingOptions(self.output))
            self.assertIsNone(result.error, result.error)
            self.assertEqual(self.jpeg.read_bytes(), original)
        finally:
            os.chmod(self.jpeg, previous_mode)

    def test_oversized_compressed_png_text_is_refused(self) -> None:
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", "Private" * (300 * 1024), zip=True)
        Image.new("RGB", (20, 14)).save(self.png, pnginfo=info)
        result = Sanitizer().process(self.png, ProcessingOptions(self.output))
        self.assertTrue(result.error)
        self.assertIsNone(result.output)

    def test_verification_detects_changed_high_bit_depth_samples(self) -> None:
        from app.core.verifier import Verifier

        source = self.root / "sixteen-bit.png"
        tampered = self.root / "tampered.png"
        Image.new("I;16", (8, 8), 1000).save(source)
        Image.new("I;16", (8, 8), 1001).save(tampered)
        # Both images clamp to the same RGBA display values; raw samples differ.
        result = Verifier().verify(
            MetadataInspector().inspect(source), tampered, ProcessingOptions(self.output)
        )
        self.assertEqual(result.state, VerificationState.FAILED)


class ToolSafetyTests(unittest.TestCase):
    def test_tool_arguments_are_literal(self) -> None:
        literal = "$(echo unsafe); & echo unsafe"
        result = run_tool([sys.executable, "-c", "import sys; print(sys.argv[1])", literal])
        self.assertEqual(result.decode().strip(), literal)

    def test_tool_failures_are_explicit(self) -> None:
        with self.assertRaises(MetaStripError):
            run_tool([sys.executable, "-c", "raise SystemExit(2)"])

    def test_tool_timeout_kills_child(self) -> None:
        with self.assertRaisesRegex(MetaStripError, "timeout"):
            run_tool([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)

    def test_running_tool_can_be_cancelled(self) -> None:
        cancel = Event()
        timer = Timer(0.15, cancel.set)
        timer.start()
        try:
            with self.assertRaises(CancelledError):
                run_tool([sys.executable, "-c", "import time; time.sleep(10)"], cancel, timeout=5)
        finally:
            timer.cancel()


class ProcessTreeSafetyTests(unittest.TestCase):
    @staticmethod
    def _command(marker: Path) -> list[str]:
        grandchild = (
            "import os,pathlib,sys,time; "
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
        )
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {grandchild!r}, sys.argv[1]]); "
            "time.sleep(30)"
        )
        return [sys.executable, "-c", parent, str(marker)]

    def _assert_descendant_stopped(self, marker: Path) -> None:
        self.assertTrue(marker.exists(), "The grandchild must start for this test to be meaningful")
        pid = int(marker.read_text())
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
            kernel.TerminateProcess.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.OpenProcess(0x100000 | 0x0001, False, pid)
            if not handle:
                self.assertEqual(ctypes.get_last_error(), 87, "Cannot inspect grandchild state")
                return
            try:
                stopped = kernel.WaitForSingleObject(handle, 1000) == 0
                if not stopped:
                    kernel.TerminateProcess(handle, 1)
                self.assertTrue(stopped, "Grandchild survived local-tool cancellation/timeout")
            finally:
                kernel.CloseHandle(handle)
        else:
            proc_stat = Path(f"/proc/{pid}/stat")
            for _ in range(100):
                try:
                    os.kill(pid, 0)
                    state = proc_stat.read_text()
                except ProcessLookupError:
                    return
                except FileNotFoundError:
                    # The process can be reaped after the probe, and /proc is optional.
                    pass
                else:
                    if state.rsplit(") ", 1)[1].startswith("Z "):
                        return
                time.sleep(0.01)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            self.fail("Grandchild survived local-tool cancellation/timeout")

    def test_descendant_reaped_while_reading_proc_stat(self) -> None:
        with TemporaryDirectory(prefix="metastrip-tree-") as directory:
            marker = Path(directory) / "grandchild.pid"
            marker.write_text("1234")
            with patch(f"{__name__}.os") as posix, patch(f"{__name__}.Path") as paths:
                posix.name = "posix"
                posix.kill.side_effect = [None, ProcessLookupError()]
                proc_stat = paths.return_value
                proc_stat.exists.return_value = True
                proc_stat.read_text.side_effect = FileNotFoundError()
                self._assert_descendant_stopped(marker)
            proc_stat.read_text.assert_called_once_with()

    def test_timeout_stops_grandchild(self) -> None:
        with TemporaryDirectory(prefix="metastrip-tree-") as directory:
            marker = Path(directory) / "grandchild.pid"
            with self.assertRaisesRegex(MetaStripError, "timeout"):
                run_tool(self._command(marker), timeout=3)
            self._assert_descendant_stopped(marker)

    def test_cancellation_stops_grandchild(self) -> None:
        with TemporaryDirectory(prefix="metastrip-tree-") as directory:
            marker = Path(directory) / "grandchild.pid"
            cancel = Event()

            def cancel_after_grandchild_starts() -> None:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                cancel.set()

            watcher = Thread(target=cancel_after_grandchild_starts, daemon=True)
            watcher.start()
            try:
                with self.assertRaises(CancelledError):
                    run_tool(self._command(marker), cancel, timeout=8)
            finally:
                watcher.join(timeout=6)
            self._assert_descendant_stopped(marker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
