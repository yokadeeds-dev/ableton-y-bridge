# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
<#
Creates the SonarQube project for this repository and a project analysis token.

    powershell -ExecutionPolicy Bypass -File scripts\sonar_setup.ps1

Asks for the SonarQube admin password (hidden input, not stored). The token is
written to .env next to the repository root as YBRIDGE_SONAR_SCAN (the file is
in .gitignore and gets an ACL for the current user only); it is not printed.
An existing project is kept; a new token is made on every run.
#>
param(
    [string]$Url = 'http://localhost:9001',
    [string]$Key = 'ableton-y-bridge',
    [string]$Name = 'Ableton Y Bridge',
    [string]$User = 'admin',
    [string]$Variable = 'YBRIDGE_SONAR_SCAN',
    [string]$EnvFile = (Join-Path (Split-Path -Parent $PSScriptRoot) '.env')
)
$ErrorActionPreference = 'Stop'

$secure = Read-Host "SonarQube password for '$User'" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $pair = [Text.Encoding]::UTF8.GetBytes("${User}:$plain")
    $headers = @{ Authorization = 'Basic ' + [Convert]::ToBase64String($pair) }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $plain = $null
}

$check = Invoke-RestMethod -Uri "$Url/api/authentication/validate" -Headers $headers
if (-not $check.valid) { throw "Login refused for '$User' at $Url" }

try {
    Invoke-RestMethod -Method Post -Uri "$Url/api/projects/create" -Headers $headers `
        -Body @{ name = $Name; project = $Key } | Out-Null
    Write-Host "Project '$Key' created."
} catch {
    $text = "$($_.ErrorDetails.Message)"
    if ($text -match 'already exists|existiert bereits') {
        Write-Host "Project '$Key' exists already, kept."
    } else { throw }
}

$tokenName = "scan-$Key-" + (Get-Date -Format 'yyyy-MM-dd_HHmmss')
$made = Invoke-RestMethod -Method Post -Uri "$Url/api/user_tokens/generate" -Headers $headers `
    -Body @{ name = $tokenName; type = 'PROJECT_ANALYSIS_TOKEN'; projectKey = $Key }
if (-not $made.token) { throw 'SonarQube returned no token' }

$line = "$Variable=$($made.token)"
$lines = @()
if (Test-Path $EnvFile) {
    $lines = @(Get-Content -Path $EnvFile | Where-Object { $_ -notmatch ("^" + [regex]::Escape($Variable) + "=") })
}
$lines += $line
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($EnvFile, (($lines -join "`n") + "`n"), $utf8NoBom)
icacls $EnvFile /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null
$made = $null
$line = $null

Write-Host "Token '$tokenName' saved in $EnvFile as $Variable (not shown)."
Write-Host "Dashboard: $Url/dashboard?id=$Key"
