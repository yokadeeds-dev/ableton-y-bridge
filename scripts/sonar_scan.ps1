# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
<#
Runs SonarScanner (Docker) on this repository against a local SonarQube.

    powershell -ExecutionPolicy Bypass -File scripts\sonar_scan.ps1
    powershell -ExecutionPolicy Bypass -File scripts\sonar_scan.ps1 -NoCoverage

Needs YBRIDGE_SONAR_SCAN in .env (scripts\sonar_setup.ps1 makes it). The token
goes to the container as an environment variable, never on a command line.
First the offline tests run under coverage.py (settings in pyproject.toml);
coverage.xml goes to the scan. Failing tests stop the scan.
#>
param(
    [string]$HostUrl = 'http://host.docker.internal:9001',
    [string]$Key = 'ableton-y-bridge',
    [string]$Variable = 'YBRIDGE_SONAR_SCAN',
    [switch]$NoCoverage,
    [string]$Python = 'python'   # the interpreter that has coverage.py
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$entry = Get-Content -Path $envFile | Where-Object { $_ -like "$Variable=*" } | Select-Object -First 1
if (-not $entry) { throw "$Variable missing in $envFile (run scripts\sonar_setup.ps1)" }

$extra = @()
if (-not $NoCoverage) {
    Push-Location $root
    # unittest writes to stderr; in PowerShell 5.1 that must not count as an error
    $ErrorActionPreference = 'Continue'
    try {
        & $Python -m coverage --version > $null 2>&1
        if ($LASTEXITCODE -ne 0) {
            $where = (& $Python -c "import sys; print(sys.executable)")
            throw "coverage.py missing for $where; pass -Python <interpreter with coverage> or -NoCoverage"
        }
        Remove-Item -Path (Join-Path $root 'coverage.xml') -ErrorAction SilentlyContinue
        & $Python -m coverage erase
        & $Python -m coverage run -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) { throw "tests failed ($LASTEXITCODE): no scan" }
        & $Python -m coverage xml -o coverage.xml
        if ($LASTEXITCODE -ne 0) { throw "coverage xml ended with $LASTEXITCODE" }
        & $Python -m coverage report --format=total
    } finally {
        Pop-Location
        $ErrorActionPreference = 'Stop'
    }
    $extra += "-Dsonar.python.coverage.reportPaths=coverage.xml"
}

$env:SONAR_TOKEN = $entry.Substring($Variable.Length + 1)
$entry = $null
try {
    docker run --rm -e SONAR_TOKEN -e "SONAR_HOST_URL=$HostUrl" `
        --add-host=host.docker.internal:host-gateway `
        -v "${root}:/usr/src" sonarsource/sonar-scanner-cli:11 `
        "-Dsonar.projectKey=$Key" `
        "-Dsonar.sources=AbletonMCP_Remote_Script,MCP_Server,analyzer,m4l,scripts,tools" `
        "-Dsonar.tests=tests" `
        "-Dsonar.exclusions=**/__pycache__/**,**/.venv/**" `
        "-Dsonar.python.version=3.11" `
        "-Dsonar.sourceEncoding=UTF-8" `
        "-Dsonar.scm.disabled=true" `
        @extra
    if ($LASTEXITCODE -ne 0) { throw "scanner ended with $LASTEXITCODE" }
} finally {
    Remove-Item Env:SONAR_TOKEN -ErrorAction SilentlyContinue
}
