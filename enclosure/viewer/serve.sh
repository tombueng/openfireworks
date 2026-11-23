#!/usr/bin/env bash
# Serve the enclosure 3D viewer locally (GLB files need http, not file://) and open it.
cd "$(dirname "$0")"
PORT="${1:-8000}"
echo "OpenFireworks enclosure viewer -> http://localhost:$PORT/"
( sleep 1; xdg-open "http://localhost:$PORT/" >/dev/null 2>&1 || true ) &
exec python3 -m http.server "$PORT"
