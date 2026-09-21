# Campaign Console setup script (Windows PowerShell)
# Usage:
#   .\setup.ps1              # full setup + tests
#   .\setup.ps1 -SkipTests   # setup only

param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Find-Python {
    $candidates = @("python", "py")
    foreach ($name in $candidates) {
        try {
            $version = & $name -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $version) {
                return @{ Command = $name; Version = $version }
            }
        } catch {
            continue
        }
    }
    return $null
}

Write-Step "Checking Python"
$pythonInfo = Find-Python
if (-not $pythonInfo) {
    Write-Error "Python was not found. Install Python 3.10+ and ensure it is on PATH."
}
Write-Host "Using $($pythonInfo.Command) ($($pythonInfo.Version))"

$venvPath = Join-Path $ProjectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$venvPip = Join-Path $venvPath "Scripts\pip.exe"

Write-Step "Creating virtual environment"
if (-not (Test-Path $venvPython)) {
    & $pythonInfo.Command -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create virtual environment."
    }
    Write-Host "Created .venv"
} else {
    Write-Host ".venv already exists"
}

Write-Step "Installing dependencies"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to upgrade pip."
}
& $venvPip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install requirements."
}
Write-Host "Dependencies installed"

Write-Step "Preparing environment file"
$envFile = Join-Path $ProjectRoot ".env"
$envExample = Join-Path $ProjectRoot ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Host "Created .env from .env.example"
    } else {
        Write-Warning ".env.example not found; skipping .env creation"
    }
} else {
    Write-Host ".env already exists (left unchanged)"
}

if (-not $SkipTests) {
    Write-Step "Running tests"
    & $venvPython -m unittest tests.test_app -v
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Tests failed."
    }
    Write-Host "All tests passed"
} else {
    Write-Host "Skipped tests (-SkipTests)"
}

Write-Step "Setup complete"
Write-Host @"

Next steps:

  1. Activate the virtual environment:
       .\.venv\Scripts\Activate.ps1

  2. Start the dev server:
       uvicorn app.main:app --reload

  3. Open the app:
       http://127.0.0.1:8000

  4. Configure your LLM provider:
       http://127.0.0.1:8000/settings/llm
     Or edit .env directly.

  5. Test the LLM connection:
       http://127.0.0.1:8000/llm/test

"@
