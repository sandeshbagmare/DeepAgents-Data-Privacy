$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$report = Join-Path $root "docs\assets\privacy-evidence.html"

function Write-Step {
    param(
        [int]$Number,
        [string]$Message
    )

    Write-Host "[$Number/5] $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($Arguments -join ' ')"
    }
}

Push-Location $root
try {
    Write-Host "Deep Agents MCP Privacy Gateway Demo" -ForegroundColor Green
    Write-Host "No model request or API key is required.`n"

    Write-Step 1 "Preparing Python environment"
    if (-not (Test-Path $venvPython)) {
        $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($null -ne $pythonLauncher) {
            Invoke-Checked $pythonLauncher.Source @("-3.11", "-m", "venv", ".venv")
        }
        else {
            $python = Get-Command python.exe -ErrorAction Stop
            Invoke-Checked $python.Source @("-m", "venv", ".venv")
        }
    }

    Write-Step 2 "Checking the local package and test dependencies"
    & $venvPython -c "import deepagents_mcp_privacy, pytest"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing missing local dependencies..."
        Invoke-Checked $venvPython @("-m", "pip", "install", "-e", ".[dev]", "--quiet")
    }

    Write-Step 3 "Checking all 34 deterministic MCP tools"
    Invoke-Checked $venvPython @("-m", "deepagents_mcp_demo.smoke")

    Write-Step 4 "Proving full-data tool execution and LLM-safe output"
    Invoke-Checked $venvPython @(
        "-m",
        "pytest",
        "tests/test_privacy.py::test_tool_processes_whole_dataset_while_llm_sees_only_synthetic_sample",
        "-q"
    )

    Write-Step 5 "Capturing process, payload, and network evidence"
    Invoke-Checked $venvPython @("scripts/capture-privacy-evidence.py")

    if (-not (Test-Path $report)) {
        throw "Evidence report was not generated: $report"
    }

    Write-Host "`nPASS: tools used complete data while the client received safe output." -ForegroundColor Green
    Write-Host "Opening $report"
    Start-Process $report
}
finally {
    Pop-Location
}