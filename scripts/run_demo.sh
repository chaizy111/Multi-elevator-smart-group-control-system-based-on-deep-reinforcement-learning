#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/project_env.sh
PROJECT_PYTHON="${ELEVATOR_PYTHON:-python}"
if [[ ! -f artifacts/models/ppo-curriculum/metadata.json ]]; then
  echo 'No ppo-curriculum model. Run the documented smoke/curriculum commands; demo never starts hidden training.' >&2
  exit 2
fi
npm --prefix frontend run build
exec "$PROJECT_PYTHON" -m elevator_control.cli serve --host "${ELEVATOR_HOST:-127.0.0.1}" --port "${ELEVATOR_PORT:-8000}"
