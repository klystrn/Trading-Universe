#!/usr/bin/env bash
# Start Trading Universe locally on macOS/Linux: backend in the background, frontend in the foreground.
# Usage (from the repo root):  ./scripts/dev.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$root/.env" ] || cp "$root/.env.example" "$root/.env"
(cd "$root/backend" && python3 -m trading_universe.cli serve) &
backend=$!
trap 'kill $backend 2>/dev/null' EXIT
cd "$root/frontend"
[ -d node_modules ] || npm install
npm run dev
