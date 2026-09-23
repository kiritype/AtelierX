[CmdletBinding()]
param(
    [string]$CloudflaredPath = $env:ATELIERX_CLOUDFLARED
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$profileDir = Join-Path $workspace '.atelierx\cloudflare'
$pidFile = Join-Path $profileDir 'tunnel.pid'

if ([string]::IsNullOrWhiteSpace($CloudflaredPath)) {
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command cloudflared -ErrorAction SilentlyContinue }
    if ($command) { $CloudflaredPath = $command.Source }
}

if ($CloudflaredPath -and (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) {
    $versionOutput = & $CloudflaredPath --version 2>&1
    Write-Output "cloudflared: $versionOutput"
} else {
    Write-Output 'cloudflared: not found on PATH or ATELIERX_CLOUDFLARED'
}

if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
    $savedPidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $savedPid = 0
    if ([int]::TryParse($savedPidText, [ref]$savedPid) -and $savedPid -gt 0) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$savedPid" -ErrorAction SilentlyContinue
        if ($process) {
            Write-Output "Named tunnel: running (PID $savedPid, started $($process.CreationDate))"
        } else {
            Write-Output "Named tunnel: PID file present (PID $savedPid) but process is not running (stale)"
        }
    } else {
        Write-Output 'Named tunnel: PID file present but invalid'
    }
} else {
    Write-Output 'Named tunnel: not running (no PID file)'
}

foreach ($port in 8190, 8192) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $result = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        $available = $result.AsyncWaitHandle.WaitOne(1000) -and $client.Connected
        Write-Output ("Local port {0}: {1}" -f $port, $(if ($available) { 'reachable (service running)' } else { 'unreachable (service not running)' }))
    } finally { $client.Dispose() }
}

$recentLogs = Get-ChildItem -LiteralPath $profileDir -Filter 'tunnel-*.stderr.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($recentLogs) {
    Write-Output "Most recent tunnel log: $($recentLogs.FullName) (last write $($recentLogs.LastWriteTime))"
}
