$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Installer = Join-Path $RepoRoot "scripts\install-plugin.ps1"
$PluginName = if ([string]::IsNullOrWhiteSpace($env:PAM_OS_PLUGIN_NAME)) { "pam-os-memory" } else { $env:PAM_OS_PLUGIN_NAME }
$SourceDir = Join-Path $RepoRoot "plugins\$PluginName"
$AssumeYes = $true
$ForwardArgs = New-Object System.Collections.Generic.List[string]

function Show-Usage {
    @"
PAM-OS local plugin installer

Usage:
  scripts\install-plugin-local.ps1 [installer-options]

Installs the REST-only pam-os-memory integration from this checkout.

Defaults passed to scripts\install-plugin.ps1:
  --source "$SourceDir"
  --repo-dir "$RepoRoot"
  --no-refresh
  --yes

Options handled by this wrapper:
  --interactive      Allow target and REST configuration prompts.
  --yes              Non-interactive install; defaults to the Codex target.
  --non-interactive  Alias for --yes.
  --installer-help   Show scripts\install-plugin.ps1 help.
  -h, --help         Show this help.

All other options are forwarded to scripts\install-plugin.ps1.
"@ | Write-Host
}

for ($i = 0; $i -lt $args.Count; $i++) {
    switch ($args[$i]) {
        "--interactive" { $AssumeYes = $false }
        "--yes" { $AssumeYes = $true }
        "--non-interactive" { $AssumeYes = $true }
        "--installer-help" {
            & $Installer --help
            exit $LASTEXITCODE
        }
        "-h" { Show-Usage; exit 0 }
        "--help" { Show-Usage; exit 0 }
        default { $ForwardArgs.Add([string]$args[$i]) }
    }
}

if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "installer not found: $Installer"
}
if (-not (Test-Path -LiteralPath (Join-Path $SourceDir ".codex-plugin\plugin.json") -PathType Leaf)) {
    throw "plugin source not found: $SourceDir"
}

$InstallArgs = @(
    "--source", $SourceDir,
    "--repo-dir", $RepoRoot,
    "--no-refresh"
)
if ($AssumeYes) {
    $InstallArgs += "--yes"
}
$InstallArgs += $ForwardArgs.ToArray()

& $Installer @InstallArgs
exit $LASTEXITCODE
