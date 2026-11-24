# Copyright (C) 2026 Yoka
# SPDX-License-Identifier: AGPL-3.0-only
<#
Runs SonarScanner (Docker) on this repository against a local SonarQube.

    powershell -ExecutionPolicy Bypass -File scripts\sonar_scan.ps1

Needs YBRIDGE_SONAR_SCAN in .env (scripts\sonar_setup.ps1 makes it). The token
goes to the container as an environment variable, never on a command line.
#>
param(
    [string]$HostUrl = 'http://host.docker.internal:9001',
    [string]$Key = 'ableton-y-bridge',
    [string]$Variable = 'YBRIDGE_SONAR_SCAN'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$entry = Get-Content -Path $envFile | Where-Object { $_ -like "$Variable=*" } | Select-Object -First 1
if (-not $entry) { throw "$Variable missing in $envFile (run scripts\sonar_setup.ps1)" }
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
        "-Dsonar.scm.disabled=true"
    if ($LASTEXITCODE -ne 0) { throw "scanner ended with $LASTEXITCODE" }
} finally {
    Remove-Item Env:SONAR_TOKEN -ErrorAction SilentlyContinue
}
