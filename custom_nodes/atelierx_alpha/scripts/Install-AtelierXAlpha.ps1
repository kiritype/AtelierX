[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$ComfyRoot,

    [ValidateNotNullOrEmpty()]
    [string]$LinkName = "atelierx_alpha"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-NormalizedPath {
    param([Parameter(Mandatory)][string]$Path)
    return (Resolve-Path -LiteralPath $Path).Path.TrimEnd([char[]]@([char]92, [char]47))
}

if ($LinkName -ne (Split-Path -Leaf $LinkName) -or $LinkName -in @(".", "..")) {
    throw "LinkName must be a single directory name."
}

$sourcePath = Get-NormalizedPath -Path (Split-Path -Parent $PSScriptRoot)
$resolvedComfyRoot = Get-NormalizedPath -Path $ComfyRoot
$customNodesPath = Join-Path $resolvedComfyRoot "custom_nodes"
if (-not (Test-Path -LiteralPath $customNodesPath -PathType Container)) {
    throw "ComfyUI custom_nodes directory was not found: $customNodesPath"
}

$targetPath = Join-Path $customNodesPath $LinkName
if (Test-Path -LiteralPath $targetPath) {
    $targetItem = Get-Item -LiteralPath $targetPath -Force
    $isJunction = (($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) -and $targetItem.LinkType -eq "Junction"
    if (-not $isJunction) {
        throw "Refusing to replace existing non-junction target: $targetPath"
    }
    $target = [string]@($targetItem.Target)[0]
    if (-not [System.IO.Path]::IsPathRooted($target)) {
        $target = Join-Path $targetItem.Parent.FullName $target
    }
    if ((Get-NormalizedPath $target) -ieq $sourcePath) {
        Write-Output "AtelierX Alpha junction already installed: $targetPath -> $sourcePath"
        return
    }
    throw "Refusing to replace existing junction with a different target: $targetPath"
}

if ($PSCmdlet.ShouldProcess($targetPath, "Create directory junction to $sourcePath")) {
    New-Item -ItemType Junction -Path $targetPath -Target $sourcePath | Out-Null
    Write-Output "Installed AtelierX Alpha junction: $targetPath -> $sourcePath"
}
