param(
    [string]$InputDir = "input_data",
    [string]$OutputDir = "",
    [string]$Cutoff = ""
)
$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $projectRoot ('outputs\run_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
}
$inputDirCandidate = if ([System.IO.Path]::IsPathRooted($InputDir)) { $InputDir } else { Join-Path $projectRoot $InputDir }
$inputDirPath = (Resolve-Path -LiteralPath $inputDirCandidate).Path
$runArguments = @('-m', 'pipeline.main', '--input-dir', $inputDirPath, '--output', $OutputDir)
if (-not [string]::IsNullOrWhiteSpace($Cutoff)) { $runArguments += @('--cutoff', $Cutoff) }
Push-Location $projectRoot
try {
    & $pythonPath @runArguments
    if ($LASTEXITCODE -ne 0) { throw "Skill ID pipeline failed with exit code $LASTEXITCODE. Read the input error above." }
    Write-Host "Results: $OutputDir"
}
finally {
    Pop-Location
}
