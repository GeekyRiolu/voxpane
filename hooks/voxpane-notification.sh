#!/usr/bin/env bash
# voxpane Notification hook — chime on the Dot when Claude needs your attention
# (e.g. a permission prompt). Arguably the single most useful outbound event.
#
# Same rules as the Stop hook: never block Claude Code — return immediately and
# do the work detached.
set -euo pipefail

payload="$(cat)"

message="Claude needs your input"
if command -v jq >/dev/null 2>&1; then
  message="$(jq -r '.message // "Claude needs your input"' <<<"$payload")"
fi

printf '{"async": true}\n'

if command -v voxpane >/dev/null 2>&1; then
  if command -v setsid >/dev/null 2>&1; then
    setsid --fork voxpane chime "$message" >/dev/null 2>&1 || true
  else
    ( voxpane chime "$message" >/dev/null 2>&1 & )
  fi
fi

exit 0
