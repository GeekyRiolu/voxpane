# voxpane Notification hook (Windows) — chime when Claude needs your attention.
# PowerShell port of voxpane-notification.sh: never block Claude Code; chime detached.
$payload = [Console]::In.ReadToEnd()
if ($env:VOXPANE_NO_HOOK) { exit 0 }

$message = "Claude needs your input"
try { $m = ($payload | ConvertFrom-Json).message; if ($m) { $message = [string]$m } } catch {}

Write-Output '{"async": true}'

if (Get-Command voxpane -ErrorAction SilentlyContinue) {
    Start-Process -FilePath "voxpane" -ArgumentList "chime", $message -WindowStyle Hidden
}
exit 0
