"""Persistence is opt-in and does not record extracted metadata values."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.models import ProcessingResult, VerificationResult, VerificationState
from app.utils.preferences import HistoryStore, PreferenceStore


def test_history_disabled_by_default(tmp_path: Path) -> None:
    assert not PreferenceStore(tmp_path / "settings.json").load().history_enabled


def test_corrupt_settings_restore_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    assert PreferenceStore(path).load().suffix == "_clean"


def test_history_expired_entries_are_pruned(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    old_date = (datetime.now(UTC) - timedelta(days=50)).isoformat()
    path.write_text(json.dumps([{"date": old_date, "filename": "expired.jpg"}]), encoding="utf-8")
    store = HistoryStore(path)
    assert store.entries(30) == []
    store.prune(30)
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_history_records_result_not_sensitive_errors(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path)
    store.append(ProcessingResult(tmp_path / "photo.jpg", error="Private sensitive error"))
    saved = path.read_text(encoding="utf-8")
    assert "Private sensitive error" not in saved
    assert store.entries()[0]["status"] == "Failed"
    store.clear()
    assert not path.exists()


def test_settings_deep_json_recovers_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[" * 2000 + "0" + "]" * 2000, encoding="utf-8")
    assert PreferenceStore(path).load().suffix == "_clean"


def test_history_prune_discards_unknown_sensitive_values(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            [
                {
                    "date": datetime.now(UTC).isoformat(),
                    "filename": "photo.jpg",
                    "private_metadata": "Private secret value",
                }
            ]
        ),
        encoding="utf-8",
    )
    store = HistoryStore(path)
    store.prune(30)
    assert "Private secret value" not in path.read_text(encoding="utf-8")


def test_history_rejects_future_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            [
                {
                    "date": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
                    "filename": "future.jpg",
                }
            ]
        ),
        encoding="utf-8",
    )
    assert HistoryStore(path).entries() == []


def test_settings_failed_replace_preserves_previous_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = PreferenceStore(path)
    preferences = store.load()
    store.save(preferences)
    original = path.read_bytes()
    preferences.suffix = "_new"
    with (
        patch("app.utils.preferences.os.replace", side_effect=PermissionError),
        pytest.raises(PermissionError),
    ):
        store.save(preferences)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_unreadable_history_is_preserved_during_automatic_writes(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    damaged = b'[{"filename": "first.jpg"},'
    path.write_bytes(damaged)
    store = HistoryStore(path)
    assert store.entries() == []
    with pytest.raises(OSError):
        store.prune(30)
    with pytest.raises(OSError):
        store.append(ProcessingResult(tmp_path / "second.jpg"))
    assert path.read_bytes() == damaged


def test_unsupported_history_entries_keep_their_status(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            [
                {
                    "date": datetime.now(UTC).isoformat(),
                    "filename": "previous.jpg",
                    "status": "Failed",
                    "verification_state": VerificationState.UNSUPPORTED.value,
                }
            ]
        ),
        encoding="utf-8",
    )
    store = HistoryStore(path)
    store.append(
        ProcessingResult(
            tmp_path / "new.jpg",
            error="Unsupported",
            verification=VerificationResult(VerificationState.UNSUPPORTED),
        )
    )
    assert [value["status"] for value in store.entries()] == ["Unsupported", "Unsupported"]
