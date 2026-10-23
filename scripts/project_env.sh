#!/usr/bin/env bash
# Source from the project root; caches and Python bytecode remain in this repository.
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export UV_CACHE_DIR="$PWD/.cache/uv"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export XDG_CACHE_HOME="$PWD/.cache"
export npm_config_cache="$PWD/.cache/npm"

mkdir -p "$PWD/.cache/tmp"
export TMPDIR="$PWD/.cache/tmp"

export PATH="$PWD/.tools/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/playwright"
