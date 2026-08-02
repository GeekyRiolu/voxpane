#!/usr/bin/env bash
# voxpane PostToolUse hook — append one line to the session activity ledger.
#
# Fast path: pure jq, no Python startup (this fires on EVERY tool call). The
# ledger is read, summarised and pruned by `voxpane` at Stop. Format & rationale:
# docs/plans/voxpane-plan.md, "The activity ledger".
set -euo pipefail

# No jq -> no ledger, but never block Claude Code.
command -v jq >/dev/null 2>&1 || exit 0

payload="$(cat)"
runtime="${XDG_RUNTIME_DIR:-/tmp/user-$(id -u)}/voxpane"
mkdir -p "$runtime"

sid="$(jq -r '.session_id // "default"' <<<"$payload")"
sid="${sid//\//_}"

# One compact JSON line; null fields are dropped so Bash calls don't carry an
# empty "path" and vice versa.
jq -c '{
  ts:   (now | floor),
  tool: .tool_name,
  path: (.tool_input.file_path // null),
  cmd:  (.tool_input.command  // null),
  exit: (.tool_response.exit_code // null)
} | with_entries(select(.value != null))' <<<"$payload" \
  >> "$runtime/ledger-${sid}.jsonl" 2>/dev/null || true

exit 0
