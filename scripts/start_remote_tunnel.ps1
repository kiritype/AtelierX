[CmdletBinding()]
param(
    [string]$CloudflaredPath = $env:ATELIERX_CLOUDFLARED
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$profileDir = Join-Path $workspace '.atelierx\cloudflare'
$tokenFile = Join-Path $profileDir 'tunnel-token.txt'
$pidFile = Join-Path $profileDir 'tunnel.pid'

New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

if (-not (Test-Path -LiteralPath $tokenFile -PathType Leaf)) {
    throw "Named tunnel token file is missing: $tokenFile"
}
if ([string]::IsNullOrWhiteSpace((Get-Content -LiteralPath $tokenFile -Raw))) {
    throw 'Named tunnel token file is empty.'
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
$tokenFull = (Resolve-Path -LiteralPath $tokenFile).Path

function Test-ManagedTunnelProcess {
    param([int]$ProcessId)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $process) { return $false }
    if (-not $process.ExecutablePath -or -not [string]::Equals($process.ExecutablePath, $cloudflaredFull, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    # Compare only the token-file path. The token value is never inspected or echoed.
    return $process.CommandLine -match [regex]::Escape('--token-file') -and $process.CommandLine -match [regex]::Escape($tokenFull)
}

if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
    $savedPidText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $savedPid = 0
    if (-not [int]::TryParse($savedPidText, [ref]$savedPid) -or $savedPid -le 0) {
        throw 'Managed tunnel PID file is invalid; inspect it before starting another tunnel.'
    }
    if (Get-Process -Id $savedPid -ErrorAction SilentlyContinue) {
        if (Test-ManagedTunnelProcess $savedPid) {
            Write-Output "Named tunnel is already running (PID $savedPid)."
            exit 0
        }
        throw 'PID file points to a different process; refusing to start another tunnel.'
    }
    Remove-Item -LiteralPath $pidFile -Force
}

$matching = @(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $_.ExecutablePath -and [string]::Equals($_.ExecutablePath, $cloudflaredFull, [StringComparison]::OrdinalIgnoreCase) -and
    $_.CommandLine -match [regex]::Escape('--token-file') -and $_.CommandLine -match [regex]::Escape($tokenFull)
})
if ($matching.Count -gt 1) { throw 'More than one matching named tunnel process exists; refusing to choose one.' }
if ($matching.Count -eq 1) {
    Set-Content -LiteralPath $pidFile -Value $matching[0].ProcessId -NoNewline
    Write-Output "Named tunnel is already running (PID $($matching[0].ProcessId))."
    exit 0
}

foreach ($port in 8190, 8192) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $result = $client.BeginConnect('127.0.0.1', $port, $null, $null)
        $available = $result.AsyncWaitHandle.WaitOne(1000) -and $client.Connected
        Write-Output ("Local port {0}: {1}" -f $port, $(if ($available) { 'reachable' } else { 'unreachable' }))
    } finally { $client.Dispose() }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdout = Join-Path $profileDir "tunnel-$stamp.stdout.log"
$stderr = Join-Path $profileDir "tunnel-$stamp.stderr.log"
$quotedTokenFile = '"' + $tokenFull + '"'
$started = Start-Process -FilePath $cloudflaredFull -ArgumentList @('tunnel', 'run', '--token-file', $quotedTokenFile) -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
if ($started.WaitForExit(1000)) {
    throw 'Named tunnel process exited immediately; inspect its log files.'
}
Set-Content -LiteralPath $pidFile -Value $started.Id -NoNewline
Write-Output "Named tunnel started (PID $($started.Id))."
