# voxpane Stop hook (Windows) — speak a summary of the finished turn, asynchronously.
# PowerShell port of voxpane-stop.sh: guard the hook loop, tell Claude Code not to wait,
# then run `voxpane speak --from-hook` detached (Start-Process) with the payload on stdin.
$payload = [Console]::In.ReadToEnd()
if ($env:VOXPANE_NO_HOOK) { exit 0 }  # nested claude for the summary must not re-fire

try { if (($payload | ConvertFrom-Json).stop_hook_active -eq $true) { exit 0 } } catch {}

Write-Output '{"async": true}'  # do not block Claude Code

if (Get-Command voxpane -ErrorAction SilentlyContinue) {
    # Detached process: pass the payload via a temp file (Start-Process has no stdin pipe).
    $tmp = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tmp, $payload)
    Start-Process -FilePath "voxpane" -ArgumentList "speak", "--from-hook" `
        -RedirectStandardInput $tmp -WindowStyle Hidden
}
exit 0
