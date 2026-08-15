# voxpane PostToolUse hook (Windows) — append one line to the session activity ledger.
# PowerShell port of voxpane-post-tool.sh: no jq; parse the hook JSON with
# ConvertFrom-Json and append a compact line to %LOCALAPPDATA%\voxpane\runtime.
$payload = [Console]::In.ReadToEnd()
if ($env:VOXPANE_NO_HOOK) { exit 0 }  # avoid recursion when voxpane invokes claude
try { $d = $payload | ConvertFrom-Json } catch { exit 0 }

$sid = if ($d.session_id) { [string]$d.session_id } else { "default" }
$sid = $sid -replace '[\\/]', '_'
$runtime = Join-Path $env:LOCALAPPDATA "voxpane\runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

$entry = [ordered]@{ ts = [int](Get-Date -UFormat %s); tool = $d.tool_name }
if ($d.tool_input.file_path) { $entry.path = $d.tool_input.file_path }
if ($d.tool_input.command)   { $entry.cmd  = $d.tool_input.command }
if ($null -ne $d.tool_response.exit_code) { $entry.exit = $d.tool_response.exit_code }

try {
    ($entry | ConvertTo-Json -Compress) |
        Add-Content -Path (Join-Path $runtime "ledger-$sid.jsonl") -Encoding utf8
} catch {}
exit 0
