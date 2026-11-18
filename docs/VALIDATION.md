# Validation

Run commands from the repository root in a Python 3.12 or newer environment.
After updating an existing checkout, run `python -m pip install -e ".[dev]"`
in that environment to pick up the current dependency requirements.

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app tests scripts
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check app tests scripts
.\.venv\Scripts\python.exe -m pytest -ra
.\.venv\Scripts\python.exe scripts/check_core_offline.py
.\.venv\Scripts\python.exe scripts/check_ui_stability.py --platform windows
```

The pytest suite covers desktop controls and worker lifecycle, content-based detection, file integrity and metadata removal, malformed input, path collisions, cancellation, and subprocess handling. Qt tests use the offscreen platform by default. The Windows stability script exercises the native desktop entry point with isolated preferences.

Install ExifTool, FFmpeg, and ffprobe to run the real tool integrations. The [Apple JPEG regression](APPLE_JPEG_MPF_REGRESSION.md) explains how to provide the optional public sample. The offline suite uses Python and Pillow and covers native image processing and external process lifetime through generated fixtures.

GitHub Actions defines Windows and Ubuntu jobs for Python 3.12 and 3.13. The local Windows run does not represent those hosted jobs, a clean-machine install, or a Windows executable build.
