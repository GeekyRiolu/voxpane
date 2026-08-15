# voxpane SessionStart hook (Windows) — start hands-free listen mode for this session.
# PowerShell port of voxpane-session-start.sh (ref-counted; reused across sessions).
$payload = [Console]::In.ReadToEnd()
if ($env:VOXPANE_NO_HOOK) { exit 0 }
if (Get-Command voxpane -ErrorAction SilentlyContinue) {
    try { $payload | voxpane listen --ensure 2>$null | Out-Null } catch {}
}
exit 0
