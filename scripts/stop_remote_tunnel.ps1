[CmdletBinding()]
param(
    [string]$CloudflaredPath = $env:ATELIERX_CLOUDFLARED
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$profileDir = Join-Path $workspace '.atelierx\cloudflare'
$tokenFile = Join-Path $profileDir 'tunnel-token.txt'
$pidFile = Join-Path $profileDir 'tunnel.pid'

if (-not (Test-Path -LiteralPath $pidFile -PathType Leaf)) {
    Write-Output 'No managed named tunnel PID file found; nothing to stop.'
    exit 0
}

if ([string]::IsNullOrWhiteSpace($CloudflaredPath)) {
    $command = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
    if (-not $command) { $command = Get-Command cloudflared -ErrorAction SilentlyContinue }
    if (-not $command) { throw 'cloudflared was not found. Set ATELIERX_CLOUDFLARED or pass -CloudflaredPath.' }
    $CloudflaredPath = $command.Source
}
if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) {
    throw 'Configured cloudflared executable was not found.'
}
$cloudflaredFull = (Resolve-Path -LiteralPath $CloudflaredPath).Path
$tokenFull = if (Test-Path -LiteralPath $tokenFile -PathType Leaf) { (Resolve-Path -LiteralPath $tokenFile).Path } else { $null }

$savedPidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
$savedPid = 0
if (-not [int]::TryParse($savedPidText, [ref]$savedPid) -or $savedPid -le 0) {
    throw 'Managed tunnel PID file is invalid; inspect it before stopping anything.'
}

$process = Get-CimInstance Win32_Process -Filter "ProcessId=$savedPid" -ErrorAction SilentlyContinue
if (-not $process) {
    Write-Output "PID $savedPid is not running. Removing stale PID file."
    Remove-Item -LiteralPath $pidFile -Force
    exit 0
}

# Only stop the process this script's own start script would recognize as the managed tunnel.
$isManaged = $process.ExecutablePath -and [string]::Equals($process.ExecutablePath, $cloudflaredFull, [StringComparison]::OrdinalIgnoreCase) -and
    $process.CommandLine -match [regex]::Escape('--token-file') -and
    ($null -eq $tokenFull -or $process.CommandLine -match [regex]::Escape($tokenFull))
if (-not $isManaged) {
    throw "PID $savedPid does not match the managed named tunnel (executable or --token-file differs); refusing to stop an unrelated process."
}

Stop-Process -Id $savedPid -ErrorAction Stop
Remove-Item -LiteralPath $pidFile -Force
Write-Output "Named tunnel stopped (was PID $savedPid)."
