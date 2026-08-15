# voxpane SessionEnd hook (Windows) — release this session; stop the listener if last.
# PowerShell port of voxpane-session-end.sh.
$payload = [Console]::In.ReadToEnd()
if ($env:VOXPANE_NO_HOOK) { exit 0 }
if (Get-Command voxpane -ErrorAction SilentlyContinue) {
    try { $payload | voxpane listen --release 2>$null | Out-Null } catch {}
}
exit 0
