#!/usr/bin/env bash
# stem-lab: build the worker's Python environment on this machine from the project's lock file.
# Sent and called by worker_env/sync.py on the desk:  bash <root>/lock/install_env.sh <root> <uv version>
# Needs no sudo and touches only <root>/. Safe to run again: when nothing changed it changes nothing.
#   <root>/lock/    pyproject.toml and uv.lock as sent from the desk, and these two scripts
#   <root>/tools/   a tiny environment that holds only uv, the same version as on the desk
#   <root>/venv/    the environment itself; machines.json points this worker's "python" at venv/bin/python
# Packages come from PyPI. uv keeps its download cache where it always does (~/.cache/uv).
# One thing the lock cannot bring: gmsh loads the system library libGLU.so.1. On Ubuntu it is in the package
# libglu1-mesa (sudo apt install libglu1-mesa). Without it gmsh installs but cannot be imported, and the report says so.
set -euo pipefail
ROOT="$1"
UV_VERSION="$2"
case "$ROOT" in
  /*/*) ;;
  *) echo "the root must be a full path below some folder, got: $ROOT"; exit 2 ;;
esac
SYSTEM_PYTHON="$(command -v python3)"
export UV_PYTHON_DOWNLOADS=never        # use this machine's own python3; never fetch another interpreter

cd "$ROOT/lock"
if [ ! -x "$ROOT/tools/bin/uv" ] || [ "$("$ROOT/tools/bin/uv" --version | awk '{print $2}')" != "$UV_VERSION" ]; then
  echo "== installing uv $UV_VERSION into $ROOT/tools"
  rm -rf "$ROOT/tools"
  "$SYSTEM_PYTHON" -m venv --without-pip "$ROOT/tools"
  "$SYSTEM_PYTHON" -m pip --python "$ROOT/tools/bin/python" install --quiet --disable-pip-version-check "uv==$UV_VERSION"
fi
echo "== $("$ROOT/tools/bin/uv" --version), system python $("$SYSTEM_PYTHON" --version 2>&1 | awk '{print $2}')"

echo "== installing from the lock (frozen: the lock is not re-resolved; no dev tools)"
UV_PROJECT_ENVIRONMENT="$ROOT/venv" "$ROOT/tools/bin/uv" sync --frozen --no-dev --python "$SYSTEM_PYTHON"
sha256sum uv.lock | awk '{print $1}' > "$ROOT/lock/installed-from.sha256"

"$ROOT/venv/bin/python" "$ROOT/lock/report_env.py" "$ROOT/lock"
