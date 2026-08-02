#!/usr/bin/env bash
# voxpane SessionStart hook — start hands-free listen mode for this Claude session.
# Ref-counted: the listener starts on the first session and is reused by the rest.
set -euo pipefail

# Avoid recursion when voxpane invokes `claude` for a summary.
if [ -n "${VOXPANE_NO_HOOK:-}" ]; then cat >/dev/null 2>&1; exit 0; fi

payload="$(cat)"
command -v voxpane >/dev/null 2>&1 || exit 0
printf '%s' "$payload" | voxpane listen --ensure >/dev/null 2>&1 || true
exit 0
