# Packaging AlphaScope as a desktop EXE

`build_exe.bat` uses PyInstaller to bundle `desktop_launcher.py` (which
starts the API server and opens `http://127.0.0.1:8000/` in your browser)
into a single `dist\AlphaScope.exe` — no Python installation needed on the
machine that runs it.

## Build it

```bash
run.bat
```

Run `run.bat` once first so `.venv` and dependencies exist, then:

```bash
build_exe.bat
```

This will:

1. Install PyInstaller into `.venv`.
2. Build `dist\AlphaScope.exe` (one file, ~220-230 MB — most of that is
   PyTorch/transformers for local news sentiment scoring).
3. Create an `AlphaScope.lnk` shortcut on your Desktop pointing at it.

Double-click the Desktop shortcut (or `dist\AlphaScope.exe` directly) any
time afterward — no terminal needed.

## Where it stores data

The frozen exe runs from `%LOCALAPPDATA%\AlphaScope\` (not wherever the exe
file itself sits), since that folder is always writable regardless of where
Windows or the user placed the `.exe`. That's where its SQLite database
would go if the storage layer is wired up, and where the FinBERT model
downloads to on first use.

## Notes

- Rebuilding after code changes: just re-run `build_exe.bat`. The Desktop
  shortcut keeps pointing at the same `dist\AlphaScope.exe` path, so it
  doesn't need to be recreated.
- The bundled app defaults to `MARKET_DATA_PROVIDER=yfinance` — real, delayed
  Yahoo Finance data for both tabs, still no API key needed. Live trading
  remains impossible; there is no order-execution code path in this codebase
  to bundle in the first place.
- `AlphaScope.spec` and `build/` are PyInstaller's intermediate artifacts
  (gitignored) — safe to delete; `build_exe.bat` regenerates them.
- The `-d noarchive` flag works around a known PyInstaller + PyTorch
  incompatibility: PyTorch's default `.pyz` (zipped archive) packaging
  breaks a module-level loop in `torch/_numpy/_ufuncs.py` (and, if that
  module is excluded instead, an `AttributeError` in one of transformers'
  optional FP8-quantization integrations that decorates itself with
  `torch._dynamo.assume_constant_result`). Storing modules as loose `.pyc`
  files instead of a zip archive avoids both — this is why the build takes
  a bit longer and the `.exe` unpacks slightly more files at startup than a
  typical PyInstaller onefile build.
