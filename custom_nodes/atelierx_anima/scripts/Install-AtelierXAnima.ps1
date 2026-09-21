[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$ComfyRoot,

    [ValidateNotNullOrEmpty()]
    [string]$LinkName = "atelierx_anima"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-NormalizedPath {
    param([Parameter(Mandatory)][string]$Path)
    return (Resolve-Path -LiteralPath $Path).Path.TrimEnd([char[]]@([char]92, [char]47))
}

function Get-JunctionTargetPath {
    param([Parameter(Mandatory)][System.IO.FileSystemInfo]$Item)

    $targets = @($Item.Target)
    if ($targets.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$targets[0])) {
        throw "Could not read a single junction target for: $($Item.FullName)"
    }

    $target = [string]$targets[0]
    if (-not [System.IO.Path]::IsPathRooted($target)) {
        $target = Join-Path -Path $Item.Parent.FullName -ChildPath $target
    }
    return Get-NormalizedPath -Path $target
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
    $isReparsePoint = ($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    if (-not $isReparsePoint -or $targetItem.LinkType -ne "Junction") {
        throw "Refusing to replace existing non-junction target: $targetPath"
    }

    $resolvedTarget = Get-JunctionTargetPath -Item $targetItem
    if ($resolvedTarget -ieq $sourcePath) {
        Write-Output "AtelierX Anima junction already installed: $targetPath -> $sourcePath"
        return
    }

    throw "Refusing to replace existing junction with a different target: $targetPath -> $resolvedTarget"
}

if ($PSCmdlet.ShouldProcess($targetPath, "Create directory junction to $sourcePath")) {
    New-Item -ItemType Junction -Path $targetPath -Target $sourcePath | Out-Null
    $targetItem = Get-Item -LiteralPath $targetPath -Force
    $resolvedTarget = Get-JunctionTargetPath -Item $targetItem
    if ($resolvedTarget -ine $sourcePath) {
        throw "Created junction does not resolve to the package source: $targetPath"
    }
    Write-Output "Installed AtelierX Anima junction: $targetPath -> $sourcePath"
}
