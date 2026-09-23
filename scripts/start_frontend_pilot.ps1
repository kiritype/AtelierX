param(
    [string]$LauncherConfig,
    [string]$StandaloneConfig,
    [string]$DiscordBridgeConfig,
    [switch]$NoGeneration,
    [switch]$NoValidation
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
$launchArgs = @('-B', (Join-Path $root 'scripts\run_frontend_pilot.py'))
if ($LauncherConfig) { $launchArgs += @('--launcher-config', $LauncherConfig) }
if ($StandaloneConfig) { $launchArgs += @('--standalone-config', $StandaloneConfig) }
if ($DiscordBridgeConfig) { $launchArgs += @('--discord-bridge-config', $DiscordBridgeConfig) }
if ($NoGeneration) { $launchArgs += '--no-generation' }
if ($NoValidation) { $launchArgs += '--no-validation' }
& $python @launchArgs
exit $LASTEXITCODE
