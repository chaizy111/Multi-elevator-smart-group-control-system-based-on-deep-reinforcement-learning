#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/project_env.sh
PROJECT_PYTHON="${ELEVATOR_PYTHON:-python}"
"$PROJECT_PYTHON" -m elevator_control.submission
npm --prefix frontend run build
exec "$PROJECT_PYTHON" -m elevator_control.cli serve --host "${ELEVATOR_HOST:-127.0.0.1}" --port "${ELEVATOR_PORT:-8000}"
