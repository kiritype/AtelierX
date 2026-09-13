[CmdletBinding(SupportsShouldProcess)]
param([Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$ComfyRoot, [ValidateNotNullOrEmpty()][string]$LinkName = "atelierx_censor")
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$sourcePath = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path.TrimEnd([char[]]@([char]92, [char]47))
$root = (Resolve-Path -LiteralPath $ComfyRoot).Path.TrimEnd([char[]]@([char]92, [char]47))
if ($LinkName -ne (Split-Path -Leaf $LinkName) -or $LinkName -in @('.', '..')) { throw "LinkName must be a single directory name." }
$customNodes = Join-Path $root 'custom_nodes'; if (-not (Test-Path -LiteralPath $customNodes -PathType Container)) { throw "ComfyUI custom_nodes directory was not found: $customNodes" }
$target = Join-Path $customNodes $LinkName
if (Test-Path -LiteralPath $target) { $item = Get-Item -LiteralPath $target -Force; if ($item.LinkType -eq 'Junction' -and ((Resolve-Path -LiteralPath ([string]@($item.Target)[0])).Path.TrimEnd([char[]]@([char]92, [char]47)) -ieq $sourcePath)) { Write-Output "AtelierX Censor junction already installed: $target"; return }; throw "Refusing to replace existing target: $target" }
if ($PSCmdlet.ShouldProcess($target, "Create directory junction to $sourcePath")) { New-Item -ItemType Junction -Path $target -Target $sourcePath | Out-Null; Write-Output "Installed AtelierX Censor junction: $target -> $sourcePath" }
