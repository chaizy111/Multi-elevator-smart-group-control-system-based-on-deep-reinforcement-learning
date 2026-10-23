#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/project_env.sh
python -c 'import sys; assert sys.version_info[:2] == (3, 11), "Activate the Python 3.11 elevator environment first"'
if command -v uv >/dev/null 2>&1; then
  PROJECT_UV="$(command -v uv)"
else
  if [[ ! -x .tools/bin/uv ]]; then
    python -m pip install --target .tools uv==0.13.5 --cache-dir .cache/pip
  fi
  PROJECT_UV="$PWD/.tools/bin/uv"
fi
UV_PYTHON_DOWNLOADS=never "$PROJECT_UV" sync --frozen --extra dev --python "$(command -v python)"
npm --prefix frontend ci --cache "$PWD/.cache/npm" --no-audit --no-fund
npm --prefix frontend run build
