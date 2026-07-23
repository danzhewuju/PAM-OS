#requires -Version 5.1

$ErrorActionPreference = "Stop"
$Client = Join-Path $PSScriptRoot "pam_client.py"

function Test-PythonCandidate {
    param([string]$Command, [string[]]$Prefix)
    try {
        & $Command @Prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

$candidates = @(
    [pscustomobject]@{ Command = "python"; Prefix = @() },
    [pscustomobject]@{ Command = "python3"; Prefix = @() },
    [pscustomobject]@{ Command = "py"; Prefix = @("-3") },
    [pscustomobject]@{ Command = "uv"; Prefix = @("run", "--no-project", "python") }
)

foreach ($candidate in $candidates) {
    if (-not (Test-PythonCandidate $candidate.Command $candidate.Prefix)) { continue }
    & $candidate.Command @($candidate.Prefix) $Client @args
    exit $LASTEXITCODE
}

Write-Error "PAM-OS requires Python 3.11 or newer (or uv)."
exit 2
