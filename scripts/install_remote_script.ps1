# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
<#
Installs the Remote Script into Ableton Live's User Library (Windows).

    powershell -ExecutionPolicy Bypass -File scripts\install_remote_script.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_remote_script.ps1 -Restore

An existing installation is moved to a dated backup folder first; -Restore
puts the most recent backup back. Restart Live afterwards (a running Live
keeps the modules it has loaded).
#>
param(
    [string]$UserLibrary = (Join-Path $env:USERPROFILE 'Documents\Ableton\User Library'),
    [string]$Name = 'AbletonMCP',
    [string]$BackupRoot = (Join-Path $env:USERPROFILE 'Documents\Ableton\Remote Script Backups'),
    [switch]$Restore
)
$ErrorActionPreference = 'Stop'
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'AbletonMCP_Remote_Script'
$scripts = Join-Path $UserLibrary 'Remote Scripts'
$target = Join-Path $scripts $Name

if ($Restore) {
    $latest = Get-ChildItem -Path $BackupRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match ("^" + [regex]::Escape($Name) + "_\d{4}-\d{2}-\d{2}_\d{6}$") } |
        Sort-Object Name | Select-Object -Last 1
    if (-not $latest) { throw "No backup of '$Name' found in $BackupRoot" }
    if (Test-Path $target) {
        $aside = Join-Path $BackupRoot ("replaced_{0}_{1}" -f $Name, (Get-Date -Format 'yyyy-MM-dd_HHmmss'))
        Move-Item -LiteralPath $target -Destination $aside
        Write-Host "Current installation moved to $aside"
    }
    Move-Item -LiteralPath $latest.FullName -Destination $target
    Write-Host "Restored $($latest.Name) to $target"
    exit 0
}

if (-not (Test-Path $source)) { throw "Source folder not found: $source" }
New-Item -ItemType Directory -Force -Path $scripts | Out-Null
if (Test-Path $target) {
    New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
    $backup = Join-Path $BackupRoot ("{0}_{1}" -f $Name, (Get-Date -Format 'yyyy-MM-dd_HHmmss'))
    Move-Item -LiteralPath $target -Destination $backup
    Write-Host "Existing installation moved to $backup"
}
New-Item -ItemType Directory -Force -Path $target | Out-Null
Get-ChildItem -Path $source -Recurse -File -Filter '*.py' | ForEach-Object {
    $relative = $_.FullName.Substring($source.Length + 1)
    $destination = Join-Path $target $relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination
}
$count = (Get-ChildItem -Path $target -Recurse -File -Filter '*.py').Count
Write-Host "Installed $count files to $target"
Write-Host "Now restart Live and select '$Name' under Settings > Link, Tempo & MIDI > Control Surface."
