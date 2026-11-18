"""Dependency discovery and integrity regressions found during the product audit."""

import copy
import json
import os
from pathlib import Path
from threading import Event

import pytest

from app.core.inspector import MetadataInspector, video_probe
from app.core.models import CancelledError, MetaStripError, ProcessingOptions
from app.core.sanitizer import Sanitizer
from app.core.verifier import Verifier
from app.utils import dependency_checker


def _executable(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name + (".exe" if os.name == "nt" else ""))
    path.write_bytes(b"synthetic executable; never run")
    path.chmod(0o755)
    return path


def _isolated_tools(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(dependency_checker, "_APP_ROOT", root)
    monkeypatch.setenv("PATH", "")
    for name in ("EXIFTOOL", "FFMPEG", "FFPROBE"):
        monkeypatch.delenv(f"METASTRIP_{name}", raising=False)


def test_app_local_tools_are_anchored_to_application(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_tools(monkeypatch, tmp_path / "app")
    tool = _executable(tmp_path / "app" / "tools" / "ffmpeg" / "bin", "ffmpeg")
    monkeypatch.chdir(tmp_path)
    assert dependency_checker.check_dependencies()["ffmpeg"] == str(tool.resolve())


def test_arbitrary_current_directory_is_not_searched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_tools(monkeypatch, tmp_path / "app")
    _executable(tmp_path, "exiftool")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", ".")
    assert dependency_checker.check_dependencies()["exiftool"] is None


def test_explicit_absolute_override_takes_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_tools(monkeypatch, tmp_path / "app")
    _executable(tmp_path / "app" / "tools", "exiftool")
    override = _executable(tmp_path / "chosen", "exiftool")
    monkeypatch.setenv("METASTRIP_EXIFTOOL", str(override))
    assert dependency_checker.check_dependencies()["exiftool"] == str(override.resolve())


def test_relative_override_does_not_execute_from_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_tools(monkeypatch, tmp_path / "app")
    _executable(tmp_path / "relative", "ffmpeg")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("METASTRIP_FFMPEG", "relative/ffmpeg.exe")
    assert dependency_checker.check_dependencies()["ffmpeg"] is None


def test_absolute_path_directory_is_supported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_tools(monkeypatch, tmp_path / "app")
    tool = _executable(tmp_path / "bin", "ffprobe")
    monkeypatch.setenv("PATH", str(tool.parent))
    assert dependency_checker.check_dependencies()["ffprobe"] == str(tool.resolve())


def test_version_diagnostics_disable_exiftool_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_tools(monkeypatch, tmp_path / "app")
    tool = _executable(tmp_path / "app" / "tools", "exiftool")
    calls = []

    def probe(arguments: list[str], cancel: Event | None, timeout: int) -> bytes:
        calls.append((arguments, timeout))
        return b"13.50\n"

    monkeypatch.setattr("app.core.tools.run_tool", probe)
    statuses = dependency_checker.dependency_diagnostics()
    assert statuses[0].status == "Installed"
    assert statuses[0].version == "13.50"
    assert calls == [([str(tool.resolve()), "-config", "", "-ver"], 5)]
    assert all(item.status == "Missing" for item in statuses[1:])


def test_failed_version_probe_has_safe_unavailable_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_tools(monkeypatch, tmp_path / "app")
    _executable(tmp_path / "app" / "tools", "ffmpeg")

    def fail(*_args, **_kwargs) -> bytes:
        raise MetaStripError("Private untrusted tool error")

    monkeypatch.setattr("app.core.tools.run_tool", fail)
    status = dependency_checker.dependency_diagnostics()[1]
    assert status.status == "Unavailable"
    assert status.version is None
    assert "Private" not in str(status)


def test_dependency_probe_can_be_cancelled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolated_tools(monkeypatch, tmp_path / "app")
    cancel = Event()
    cancel.set()
    with pytest.raises(CancelledError):
        dependency_checker.dependency_diagnostics(cancel)


def test_unrelated_executable_version_is_not_reported_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_tools(monkeypatch, tmp_path / "app")
    _executable(tmp_path / "app" / "tools", "ffmpeg")
    monkeypatch.setattr("app.core.tools.run_tool", lambda *_args, **_kwargs: b"Unrelated program")
    assert dependency_checker.dependency_diagnostics()[1].status == "Unavailable"


def test_removed_categories_report_only_scanned_fields(jpeg_file: Path, tmp_path: Path) -> None:
    result = Sanitizer().process(jpeg_file, ProcessingOptions(tmp_path / "clean"))
    assert result.error is None, result.error
    assert set(result.verification.removed_categories) == {"Author", "Camera", "Dates", "Software"}


@pytest.mark.parametrize("payload", [b"{}", b"[{}, {}]", b"[1]", b'"bad"'])
def test_malformed_exiftool_json_is_a_safe_inspection_error(
    monkeypatch: pytest.MonkeyPatch, jpeg_file: Path, payload: bytes
) -> None:
    monkeypatch.setattr("app.core.inspector.check_dependencies", lambda: {"exiftool": "tool"})
    monkeypatch.setattr("app.core.inspector.run_exiftool", lambda *_args: payload)
    with pytest.raises(MetaStripError, match="invalid metadata"):
        MetadataInspector().inspect(jpeg_file)


@pytest.mark.parametrize("streams", ["unexpected string", [1], [], {"index": 0}])
def test_ffprobe_schema_is_validated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, streams: object
) -> None:
    monkeypatch.setattr("app.core.inspector.check_dependencies", lambda: {"ffprobe": "tool"})
    payload = json.dumps({"streams": streams}).encode()
    monkeypatch.setattr("app.core.inspector.run_tool", lambda *_args: payload)
    with pytest.raises(MetaStripError):
        video_probe(tmp_path / "video.mp4")


def test_pdf_integrity_detects_invisible_text_changes(tmp_path: Path) -> None:
    import pymupdf

    source = tmp_path / "source.pdf"
    output = tmp_path / "tampered.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=200, height=200)
        page.insert_text((20, 40), "Visible content")
        document.save(source)
        page.insert_text((20, 80), "Invisible changed content", render_mode=3)
        document.save(output)
    assert not Verifier._pdf_equal(source, output, None)


def test_video_integrity_detects_changed_audio_sync(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "output.mp4"
    original = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "start_time": "0.0", "duration": "10"},
            {"codec_type": "audio", "codec_name": "aac", "start_time": "0.04", "duration": "10"},
        ]
    }
    changed = copy.deepcopy(original)
    changed["streams"][1]["start_time"] = "1.04"
    monkeypatch.setattr(
        "app.core.verifier.video_probe",
        lambda path, _cancel: original if path == source else changed,
    )
    monkeypatch.setattr("app.core.verifier.check_dependencies", lambda: {"ffmpeg": "tool"})
    monkeypatch.setattr("app.core.verifier.run_tool", lambda *_args: b"same packet hashes")
    assert not Verifier._video_equal(source, output, None)
