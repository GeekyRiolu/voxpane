#!/usr/bin/env bash
# voxpane SessionEnd hook — release this session; stop the listener if it was last.
set -euo pipefail

# Avoid recursion when voxpane invokes `claude` for a summary.
if [ -n "${VOXPANE_NO_HOOK:-}" ]; then cat >/dev/null 2>&1; exit 0; fi

payload="$(cat)"
command -v voxpane >/dev/null 2>&1 || exit 0
printf '%s' "$payload" | voxpane listen --release >/dev/null 2>&1 || true
exit 0
