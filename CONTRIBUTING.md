# Contributing to MetaStrip

Use Python 3.12 or newer. Create a virtual environment and install the development
dependencies from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -ra
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check app tests scripts
```

On Linux/macOS, create the environment with `python -m venv .venv` using Python
3.12 or newer and use `.venv/bin/python`. CI runs GUI tests offscreen.
Install ExifTool, FFmpeg and ffprobe separately to exercise their integration paths;
tests must skip unavailable external tools with an explicit reason.

Keep processing services independent of Qt and use the shared immutable models in
`app/core/models.py`. Communicate with background workers through Qt signals.
Never modify source files in place, silently re-encode media, execute metadata as
code, log sensitive values, or introduce networking/telemetry into processing.

For a change, explain the concrete problem, resulting behavior, and actual checks
run. Generate synthetic fixtures instead of committing private files. Changes to
sanitization or verification should cover original preservation, content integrity,
failure cleanup and honest verification states. Do not add a success state when a
check could not run. Include format-specific limitations in the README.

Before changing bundled dependencies or build options, review
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Keep code, identifiers, technical
documentation and commit messages in English.

Please report security-sensitive problems privately to a maintainer once the
project has a published security contact. Do not attach files containing real
personal metadata to a public issue. Until a contact is established, provide a
minimal synthetic reproducer and omit private details.
