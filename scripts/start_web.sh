#!/usr/bin/env bash
# Start the LogAgent-RCA web application on 127.0.0.1:8765 (local mode).
# Pass extra arguments through, e.g.  ./scripts/start_web.sh --auth-file users.json
set -euo pipefail
cd "$(dirname "$0")/.."
if ! curl -s --max-time 3 http://127.0.0.1:11434/api/version > /dev/null; then
  echo "warning: Ollama is not reachable at 127.0.0.1:11434; pages will load but analyses will fail." >&2
fi
exec .venv/bin/python -m logagent_rca serve --config configs/app.yaml --host 127.0.0.1 --port "${PORT:-8765}" "$@"
