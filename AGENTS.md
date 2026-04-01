# AGENTS.md — stt-cursor

## Project Overview

**stt-cursor** is a continuous dictation tool for Linux that captures microphone audio via PulseAudio/PipeWire, performs offline speech-to-text with Vosk, and pastes recognized text at the cursor position using `xclip` + `xdotool`.

- **Language**: Python 3.14.2
- **Package manager**: `uv`
- **Target platform**: Arch Linux / Xfce / PulseAudio or PipeWire (X11)
- **Entry point**: `main.py`
- **Auxiliary**: `dictation-toggle.sh` (bash toggle script for global hotkey binding)

## Commands

```bash
uv sync              # Install dependencies (creates .venv)
uv add <package>     # Add a dependency to pyproject.toml
uv run python main.py  # Run the application
.venv/bin/python main.py  # Run directly (faster)
bash dictation-toggle.sh  # Toggle dictation on/off (bind to hotkey)
```

### Testing

**No test framework is currently configured.** If adding tests:
- Use `pytest` (install with `uv add --dev pytest`)
- Place tests in a `tests/` directory or as `test_*.py` files
- Run with `uv run pytest` or `uv run pytest tests/test_file.py` for a single test
- Run a single test: `uv run pytest tests/test_file.py::test_name -v`

### Linting & Formatting

**No linter or formatter is currently configured.** If adding tooling:
- Recommended: `uv add --dev ruff` (lint + format)
- Run: `uv run ruff check .` / `uv run ruff format .`

## Code Style

### Python (`main.py`)

**Imports**
- Standard library imports first, grouped together (no blank lines between stdlib)
- Blank line separator before third-party imports
- No `__future__` imports currently; add if using newer features

**Naming**
- Functions: `snake_case` (`paste_text`, `process_text`, `cleanup`, `main`)
- Constants: `UPPER_SNAKE_CASE` (`SAMPLE_RATE`, `MODEL_PATH`, `PID_FILE`)
- Variables: `snake_case`

**Types**
- Type hints on function signatures where practical (`def paste_text(text: str) -> None:`)
- Use built-in types (`str`, `None`) — no `typing` module imports yet

**Error Handling**
- Use `check=True` on `subprocess.run` for strict error checking
- Graceful `KeyboardInterrupt` handling in main loop
- Signal handlers for `SIGTERM` and `SIGINT` via `signal.signal()`
- Catch specific exceptions (`FileNotFoundError`) rather than bare `except`
- Use `try/finally` for cleanup guarantees

**Docstrings**
- Russian language (matching project convention)
- Triple-double-quote, single-line for simple functions

**Structure**
- Single-file application; no packages/modules
- Functions defined before `main()`
- `if __name__ == "__main__":` guard required
- Global constants at module level after imports

### Bash (`dictation-toggle.sh`)

- Shebang: `#!/usr/bin/env bash`
- Comments in Russian
- Functions for `start_dictation` and `stop_dictation`
- Exports `DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`, `PATH` for hotkey compatibility
- Logs to `/tmp/stt-cursor.log` for debugging
- Uses `notify-send` for user feedback (2000ms duration)

## Project Structure

```
stt-cursor/
  main.py                  # Entry point: Vosk STT loop → xclip → xdotool
  dictation-toggle.sh      # Bash toggle script (bind to global hotkey)
  pyproject.toml           # uv project config
  uv.lock                  # Pinned dependencies
  .python-version          # Python 3.14.2
  .gitignore               # temp/, __pycache__, .env, model/
  model/                   # Vosk speech recognition model (gitignored)
```

## System Dependencies

These are **not** managed by uv and must be installed on the host:
- `vosk` — offline speech recognition (Python package, via uv)
- `parec` — PulseAudio/PipeWire audio capture
- `xclip` — clipboard manipulation (X11)
- `xdotool` — X11 keyboard simulation
- `notify-send` — desktop notifications (libnotify)

## Conventions for Contributions

1. Keep the single-file structure unless complexity demands splitting
2. Preserve Russian comments/docstrings for consistency
3. Always use `check=True` on subprocess calls
4. Handle `SIGTERM`/`SIGINT` gracefully with cleanup
5. PID file at `/tmp/stt-cursor.pid` for toggle script coordination
6. Do not commit the `model/` directory (gitignored)
