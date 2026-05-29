param(
    [string]$ApiKey = "",
    [string]$ProxyUrl = "",
    [ValidateSet("Official", "Npm")]
    [string]$Method = "Official",
    [switch]$SkipApiKey,
    [switch]$SkipNetworkCheck,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-RequestOptions {
    if ([string]::IsNullOrWhiteSpace($ProxyUrl)) {
        return @{}
    }

    return @{
        Proxy = $ProxyUrl
        ProxyUseDefaultCredentials = $true
    }
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Set-ProxyEnvironment {
    if ([string]::IsNullOrWhiteSpace($ProxyUrl)) {
        return
    }

    Write-Step "Using proxy: $ProxyUrl"
    $env:HTTP_PROXY = $ProxyUrl
    $env:HTTPS_PROXY = $ProxyUrl
    $env:http_proxy = $ProxyUrl
    $env:https_proxy = $ProxyUrl

    if (Test-Command "npm") {
        npm config set proxy $ProxyUrl | Out-Null
        npm config set https-proxy $ProxyUrl | Out-Null
    }
}

function Test-RequiredNetwork {
    if ($SkipNetworkCheck) {
        return
    }

    Write-Step "Checking required network access"

    $targets = @(
        "https://chatgpt.com/codex/install.ps1",
        "https://github.com",
        "https://api.openai.com"
    )

    $failed = @()
    $requestOptions = Get-RequestOptions

    foreach ($target in $targets) {
        try {
            Invoke-WebRequest -Uri $target -Method Get -TimeoutSec 15 -UseBasicParsing @requestOptions | Out-Null
            Write-Host "OK  $target" -ForegroundColor Green
        } catch {
            $response = $_.Exception.Response
            if ($response -and [int]$response.StatusCode -ge 400) {
                Write-Host "OK  $target returned HTTP $([int]$response.StatusCode)" -ForegroundColor Green
            } else {
                Write-Host "BAD $target" -ForegroundColor Yellow
                $failed += $target
            }
        }
    }

    if ($failed.Count -gt 0) {
        $message = "Network check failed. Configure a proxy, for example -ProxyUrl http://127.0.0.1:7890, then retry."
        throw $message
    }
}

function Install-CodexOfficial {
    Write-Step "Installing Codex with the official installer"
    $requestOptions = Get-RequestOptions
    Invoke-RestMethod "https://chatgpt.com/codex/install.ps1" @requestOptions | Invoke-Expression
}

function Install-CodexNpm {
    Write-Step "Installing Codex with npm"
    if (-not (Test-Command "npm")) {
        throw "npm is not installed. Install Node.js first, or use -Method Official."
    }

    npm install -g @openai/codex
}

Write-Host "Codex deployment script" -ForegroundColor Green
Write-Host "Method: $Method"

if ($PSVersionTable.PSEdition -ne "Desktop" -and $PSVersionTable.PSEdition -ne "Core") {
    throw "Unsupported PowerShell edition."
}

if (-not $SkipApiKey) {
    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        $ApiKey = Read-Host "OpenAI API key, leave empty to skip"
    }

    if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
        Write-Step "Saving OPENAI_API_KEY for the current Windows user"
        [Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $ApiKey, "User")
        $env:OPENAI_API_KEY = $ApiKey
    }
}

Set-ProxyEnvironment
Test-RequiredNetwork
Refresh-Path

if ((Test-Command "codex") -and -not $Force) {
    Write-Step "Codex is already installed"
    codex --version
    Write-Host ""
    Write-Host "Use -Force to reinstall." -ForegroundColor Yellow
    exit 0
}

if ($Method -eq "Official") {
    Install-CodexOfficial
} else {
    Install-CodexNpm
}

Refresh-Path

Write-Step "Verifying Codex installation"
if (-not (Test-Command "codex")) {
    throw "Codex was installed, but the codex command is not available in PATH. Open a new terminal and run: codex --version"
}

codex --version

Write-Host ""
Write-Host "Codex deployment completed." -ForegroundColor Green
Write-Host "Open a new PowerShell window and run: codex"
