#!/usr/bin/env bash
# voxpane SessionEnd hook — release this session; stop the listener if it was last.
set -euo pipefail

payload="$(cat)"
command -v voxpane >/dev/null 2>&1 || exit 0
printf '%s' "$payload" | voxpane listen --release >/dev/null 2>&1 || true
exit 0
