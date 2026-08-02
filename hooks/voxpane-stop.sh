#!/usr/bin/env bash
# voxpane Stop hook — speak a summary of the finished turn, asynchronously.
#
# Rules (docs/plans/voxpane-plan.md, "Outbound"):
#   * guard on stop_hook_active, or risk a hook loop;
#   * NEVER block Claude Code — return immediately, do the work detached;
#   * gating (did this turn do real work? quiet hours? a bare question?) lives in
#     `voxpane speak`, not here.
set -euo pipefail

payload="$(cat)"

# Guard against a hook loop.
if command -v jq >/dev/null 2>&1; then
  if [[ "$(jq -r '.stop_hook_active // false' <<<"$payload")" == "true" ]]; then
    exit 0
  fi
fi

# Tell Claude Code not to wait on us.
printf '{"async": true}\n'

# Do the real work fully detached so the agent never stalls on TTS/synthesis.
# (`setsid` gives a cleaner detach where available; the subshell background is
# the portable floor.)
if command -v voxpane >/dev/null 2>&1; then
  if command -v setsid >/dev/null 2>&1; then
    setsid --fork bash -c 'voxpane speak --from-hook' <<<"$payload" >/dev/null 2>&1 || true
  else
    ( voxpane speak --from-hook <<<"$payload" >/dev/null 2>&1 & )
  fi
fi

exit 0
