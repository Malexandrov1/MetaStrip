"""Small, local-only preferences and opt-in history stores."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.models import ProcessingResult, VerificationState

_HISTORY_KEYS = (
    "filename",
    "date",
    "format",
    "status",
    "output",
    "verification",
    "verification_state",
)


def _read_json(path: Path, max_bytes: int) -> object:
    """Bound locally stored data so a damaged file cannot exhaust the UI process."""
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Local configuration exceeds the supported size.")
    return json.loads(data.decode("utf-8"))


def valid_suffix(suffix: str) -> bool:
    return (
        bool(suffix)
        and len(suffix) <= 60
        and not any(char in suffix for char in '<>:"/\\|?*')
        and not suffix.endswith((".", " "))
        and not any(ord(char) < 32 for char in suffix)
    )


def config_directory() -> Path:
    """Return a platform-appropriate per-user application directory."""
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "MetaStrip"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "metastrip"


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".metastrip-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=True)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass
class Preferences:
    output_dir: str = ""
    suffix: str = "_clean"
    theme: str = "Dark"
    preserve_color_profile: bool = True
    remove_pdf_annotations: bool = False
    history_enabled: bool = False
    history_retention_days: int = 30


class PreferenceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_directory() / "settings.json"

    def load(self) -> Preferences:
        try:
            data = _read_json(self.path, 64 * 1024)
            if not isinstance(data, dict):
                return Preferences()
            defaults = asdict(Preferences())
            valid = {
                key: value
                for key, value in data.items()
                if key in defaults and type(value) is type(defaults[key])
            }
            prefs = Preferences(**valid)
            prefs.history_retention_days = max(0, min(365, prefs.history_retention_days))
            if prefs.theme not in {"Dark", "Light"}:
                prefs.theme = "Dark"
            if not valid_suffix(prefs.suffix):
                prefs.suffix = "_clean"
            return prefs
        except (OSError, ValueError, TypeError, RecursionError):
            return Preferences()

    def save(self, preferences: Preferences) -> None:
        _write_json(self.path, asdict(preferences))


class HistoryStore:
    """Keep result summaries only: never extracted metadata values."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_directory() / "history.json"

    def _load(self) -> list[object]:
        try:
            values = _read_json(self.path, 8 * 1024 * 1024)
            if not isinstance(values, list):
                raise ValueError("Expected a list of history entries.")
            return values
        except FileNotFoundError:
            return []
        except (ValueError, RecursionError) as exc:
            raise OSError("The local history file could not be read safely.") from exc

    @staticmethod
    def _retained(values: list[object], retention_days: int) -> list[dict[str, str]]:
        now = datetime.now(UTC)
        cutoff = (
            now - timedelta(days=max(1, min(365, retention_days)))
            if retention_days != 0
            else datetime.min.replace(tzinfo=UTC)
        )
        entries = []
        for entry in values:
            if not isinstance(entry, dict) or not all(
                isinstance(value, str) for value in entry.values()
            ):
                continue
            try:
                timestamp = datetime.fromisoformat(entry.get("date", ""))
                if timestamp.tzinfo and cutoff <= timestamp <= now:
                    record = {key: entry.get(key, "") for key in _HISTORY_KEYS}
                    if record["verification_state"] == VerificationState.UNSUPPORTED:
                        record["status"] = VerificationState.UNSUPPORTED.value
                    entries.append((timestamp, record))
            except ValueError:
                continue
        entries.sort(key=lambda entry: entry[0], reverse=True)
        return [record for _, record in entries[:1000]]

    def entries(self, retention_days: int = 30) -> list[dict[str, str]]:
        try:
            return self._retained(self._load(), retention_days)
        except OSError:
            return []

    def prune(self, retention_days: int) -> None:
        values = self._load()
        retained = self._retained(values, retention_days)
        if retained != values:
            _write_json(self.path, retained)

    def append(self, result: ProcessingResult, retention_days: int = 30) -> None:
        entries = self._retained(self._load(), retention_days)
        entries.insert(
            0,
            {
                "filename": result.source.name,
                "date": datetime.now(UTC).isoformat(timespec="seconds"),
                "format": result.format.value if result.format else "Unknown",
                "status": result.status,
                "output": str(result.output or ""),
                "verification": "; ".join(result.verification.checks),
                "verification_state": result.verification.state.value,
            },
        )
        _write_json(self.path, entries[:1000])

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
