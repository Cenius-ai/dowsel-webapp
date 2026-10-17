#!/usr/bin/env bash
# Dowsel setup: install the project-level dependency (the test runner), put the
# `dowsel` command on PATH, self-check, then EXIT. It never installs system
# packages and never starts the tool - Dowsel is a CLI, you run it yourself.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo "Dowsel setup"
echo "  python : $("$PYTHON" --version 2>&1)"
echo "  project: $(pwd)"

# 1. Python floor. Dowsel targets 3.8+; the sandbox and this build use 3.11.
"$PYTHON" - <<'PYCHECK'
import sys
if sys.version_info < (3, 8):
    raise SystemExit(f"dowsel needs Python 3.8 or newer, found {sys.version.split()[0]}")
PYCHECK

# 2. Package tooling. Best effort: a machine that is offline but already has a
#    working pip/setuptools should still finish setup.
if ! "$PYTHON" -m pip install --upgrade --quiet pip setuptools wheel; then
    echo "  note   : could not refresh pip/setuptools/wheel (offline?); continuing"
fi

# 3. Project dependency: pytest, the declared test runner. Skipped when the
#    interpreter already has it, so an offline machine still installs cleanly.
if "$PYTHON" -c "import pytest" >/dev/null 2>&1; then
    echo "  deps   : pytest already available ($("$PYTHON" -m pytest --version 2>&1 | head -n 1))"
else
    "$PYTHON" -m pip install --quiet -r requirements.txt
    echo "  deps   : installed requirements.txt"
fi

# 4. The `dowsel` console command. Convenience only - `python3 dowsel.py` always
#    works - so a locked-down site-packages does not fail the whole setup.
if "$PYTHON" -m pip install --quiet --no-deps --no-build-isolation -e . >/dev/null 2>&1; then
    echo "  command: dowsel on PATH"
else
    echo "  note   : could not install the 'dowsel' command; use 'python3 dowsel.py' instead"
fi

# 5. Loud self-check: a broken environment fails here, not at the bench.
"$PYTHON" -c "import dowsel; print('  check  : dowsel', dowsel.__version__, 'imports cleanly')"
"$PYTHON" dowsel.py --version >/dev/null

echo
echo "Setup complete (nothing was started)."
echo "  run  : python3 dowsel.py --help   (or: dowsel --help)"
echo "  demo : bash demo.sh"
echo "  test : python3 -m pytest"
