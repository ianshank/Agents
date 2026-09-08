#requires -Version 5.1
<#
.SYNOPSIS
  Mechanical Tier A verification gate.
#>
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Py = @(
    [System.IO.Path]::Combine($RepoRoot, '.venv', 'Scripts', 'python.exe'),
    [System.IO.Path]::Combine($RepoRoot, '.venv', 'bin', 'python')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Py) { $Py = "python" }

& $Py (Join-Path $PSScriptRoot 'verify_tier_a.py')
exit $LASTEXITCODE
