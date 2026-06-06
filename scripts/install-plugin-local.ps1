#requires -Version 5.1

$ErrorActionPreference = "Stop"
$CliArgs = $args

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $ScriptDir ".."))
$Installer = Join-Path $RepoRoot "scripts\install-plugin.ps1"
$PluginName = if ([string]::IsNullOrWhiteSpace($env:PAM_OS_PLUGIN_NAME)) { "pam-os-memory" } else { $env:PAM_OS_PLUGIN_NAME }
$SourceDir = Join-Path (Join-Path $RepoRoot "plugins") $PluginName

$AssumeYes = $true
$HasTarget = $false
$HasMode = $false
$PromptTarget = $true
$PromptMode = $true
$Passthrough = @()
$SelectedTargets = @()
$SelectedMode = ""
$RestUrl = if ([string]::IsNullOrWhiteSpace($env:PAM_OS_REST_URL)) { "http://127.0.0.1:8765" } else { $env:PAM_OS_REST_URL }
$RestUsername = if ([string]::IsNullOrWhiteSpace($env:PAM_OS_REST_USERNAME)) { "" } else { $env:PAM_OS_REST_USERNAME }
$RestPassword = if ([string]::IsNullOrWhiteSpace($env:PAM_OS_REST_PASSWORD)) { "" } else { $env:PAM_OS_REST_PASSWORD }

function Stop-LocalInstall {
    param([string]$Message)
    Write-Error "error: $Message"
    exit 1
}

function Test-CanPrompt {
    try {
        return [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
    }
    catch {
        return [Environment]::UserInteractive
    }
}

function Read-User {
    param([string]$Prompt)
    if (-not (Test-CanPrompt)) {
        Stop-LocalInstall "Interactive target selection requires a user session. Re-run with --target, --all, or --yes."
    }
    return Read-Host $Prompt
}

function Prompt-Value {
    param(
        [string]$Prompt,
        [string]$Default
    )
    $promptText = if ([string]::IsNullOrWhiteSpace($Default)) {
        "$Prompt (leave empty for none)"
    } else {
        "$Prompt [$Default]"
    }
    $reply = Read-User $promptText
    if ([string]::IsNullOrWhiteSpace($reply)) {
        return $Default
    }
    return $reply
}

function Prompt-Secret {
    param(
        [string]$Prompt,
        [string]$Default
    )
    $secure = Read-Host "$Prompt (leave empty for none)" -AsSecureString
    if ($secure.Length -eq 0) {
        return $Default
    }

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Select-InstallTargets {
    Write-Host ""
    Write-Host "Install targets:"
    Write-Host "  1) codex     - Codex plugin + MCP + global skill fallback"
    Write-Host "  2) claude    - Claude Code global skill + MCP"
    Write-Host "  3) opencode  - OpenCode guidance"
    Write-Host "  4) hermes    - Hermes MCP config + guidance"
    Write-Host "  5) all"
    Write-Host ""
    Write-Host "Select one or more targets, separated by commas or spaces."

    while ($true) {
        $selection = Read-User "Selection [1]"
        if ([string]::IsNullOrWhiteSpace($selection)) {
            $selection = "1"
        }

        $script:SelectedTargets = @()
        $valid = $true

        foreach ($item in ($selection -replace ",", " " -split "\s+" | Where-Object { $_ })) {
            switch -Regex ($item) {
                "^(1|codex)$" {
                    $script:SelectedTargets += "codex"
                    continue
                }
                "^(2|claude|claude-code)$" {
                    $script:SelectedTargets += "claude"
                    continue
                }
                "^(3|opencode)$" {
                    $script:SelectedTargets += "opencode"
                    continue
                }
                "^(4|hermes)$" {
                    $script:SelectedTargets += "hermes"
                    continue
                }
                "^(5|all)$" {
                    $script:SelectedTargets = @("all")
                    continue
                }
                default {
                    Write-Warning "Unknown target: $item"
                    $valid = $false
                    break
                }
            }
        }

        if ($valid -and $script:SelectedTargets.Count -gt 0) {
            return
        }

        Write-Host "Please select at least one valid target."
    }
}

function Select-RuntimeMode {
    Write-Host ""
    Write-Host "Runtime mode:"
    Write-Host "  1) cli  - register local MCP runtime; CLI fallback remains available"
    Write-Host "  2) rest - use a running PAM-OS REST server and remove managed local MCP"

    while ($true) {
        $modeChoice = Read-User "Selection [1]"
        if ([string]::IsNullOrWhiteSpace($modeChoice)) {
            $modeChoice = "1"
        }

        switch ($modeChoice) {
            "1" {
                $script:SelectedMode = "cli"
                return
            }
            "cli" {
                $script:SelectedMode = "cli"
                return
            }
            "2" {
                $script:SelectedMode = "rest"
                $script:RestUrl = Prompt-Value "PAM-OS REST URL" $script:RestUrl
                $script:RestUsername = Prompt-Value "REST username" $script:RestUsername
                $script:RestPassword = Prompt-Secret "REST password" $script:RestPassword
                if ([string]::IsNullOrWhiteSpace($script:RestUrl)) {
                    Stop-LocalInstall "REST URL must not be empty."
                }
                return
            }
            "rest" {
                $script:SelectedMode = "rest"
                $script:RestUrl = Prompt-Value "PAM-OS REST URL" $script:RestUrl
                $script:RestUsername = Prompt-Value "REST username" $script:RestUsername
                $script:RestPassword = Prompt-Secret "REST password" $script:RestPassword
                if ([string]::IsNullOrWhiteSpace($script:RestUrl)) {
                    Stop-LocalInstall "REST URL must not be empty."
                }
                return
            }
            default { Write-Warning "Invalid runtime mode: $modeChoice" }
        }
    }
}

function Show-Usage {
    @"
PAM-OS local plugin installer for Windows

Usage:
  .\scripts\install-plugin-local.ps1 [installer-options]

Installs the pam-os-memory plugin from this local checkout instead of fetching
from GitHub. By default it asks which target to install, then accepts replace
prompts non-interactively for fast local debugging.

Defaults passed to scripts\install-plugin.ps1:
  --source "$SourceDir"
  --repo-dir "$RepoRoot"
  --no-refresh
  --yes

If no interactive session is available and no target is provided, it falls back
to --target codex.

Examples:
  .\scripts\install-plugin-local.ps1
  .\scripts\install-plugin-local.ps1 --all
  .\scripts\install-plugin-local.ps1 --target claude
  .\scripts\install-plugin-local.ps1 --interactive
  .\scripts\install-plugin-local.ps1 --yes
  .\scripts\install-plugin-local.ps1 --no-init

Options handled by this wrapper:
  --interactive      Do not pass --yes; allow the installer to prompt.
  --yes              Fully non-interactive legacy default: install codex with CLI mode.
  --non-interactive  Alias for --yes.
  --installer-help   Show scripts\install-plugin.ps1 help.
  -h, --help         Show this help.

All other options are forwarded to scripts\install-plugin.ps1.
"@ | Write-Host
}

for ($i = 0; $i -lt $CliArgs.Count; $i++) {
    $arg = $CliArgs[$i]
    switch ($arg) {
        "--interactive" {
            $AssumeYes = $false
            $PromptTarget = $false
            $PromptMode = $false
        }
        "--yes" {
            $AssumeYes = $true
            $PromptTarget = $false
            $PromptMode = $false
        }
        "--non-interactive" {
            $AssumeYes = $true
            $PromptTarget = $false
            $PromptMode = $false
        }
        "--installer-help" {
            if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
                Stop-LocalInstall "installer not found: $Installer"
            }
            & $Installer --help
            exit $LASTEXITCODE
        }
        "--target" {
            if ($i + 1 -ge $CliArgs.Count -or [string]::IsNullOrWhiteSpace($CliArgs[$i + 1]) -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--target requires a value"
            }
            $HasTarget = $true
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--mode" {
            if ($i + 1 -ge $CliArgs.Count -or [string]::IsNullOrWhiteSpace($CliArgs[$i + 1]) -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--mode requires a value"
            }
            $HasMode = $true
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--runtime" {
            if ($i + 1 -ge $CliArgs.Count -or [string]::IsNullOrWhiteSpace($CliArgs[$i + 1]) -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--runtime requires a value"
            }
            $HasMode = $true
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--rest-url" {
            if ($i + 1 -ge $CliArgs.Count -or [string]::IsNullOrWhiteSpace($CliArgs[$i + 1]) -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--rest-url requires a value"
            }
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--rest-username" {
            if ($i + 1 -ge $CliArgs.Count -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--rest-username requires a value"
            }
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--rest-user" {
            if ($i + 1 -ge $CliArgs.Count -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--rest-user requires a value"
            }
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--rest-password" {
            if ($i + 1 -ge $CliArgs.Count -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--rest-password requires a value"
            }
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--codex" {
            $HasTarget = $true
            $Passthrough += $arg
        }
        "--claude" {
            $HasTarget = $true
            $Passthrough += $arg
        }
        "--opencode" {
            $HasTarget = $true
            $Passthrough += $arg
        }
        "--hermes" {
            $HasTarget = $true
            $Passthrough += $arg
        }
        "--all" {
            $HasTarget = $true
            $Passthrough += $arg
        }
        "-h" {
            Show-Usage
            exit 0
        }
        "--help" {
            Show-Usage
            exit 0
        }
        default {
            $Passthrough += $arg
        }
    }
}

if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    Stop-LocalInstall "installer not found: $Installer"
}

if (-not (Test-Path -LiteralPath (Join-Path (Join-Path $SourceDir ".codex-plugin") "plugin.json") -PathType Leaf)) {
    Stop-LocalInstall "plugin source not found: $SourceDir"
}

$InstallerArgs = @(
    "--source", $SourceDir,
    "--repo-dir", $RepoRoot,
    "--no-refresh"
)

if (-not $HasTarget) {
    if ($PromptTarget -and (Test-CanPrompt)) {
        Select-InstallTargets
        foreach ($target in $SelectedTargets) {
            $InstallerArgs += @("--target", $target)
        }
    }
    elseif ($AssumeYes) {
        $InstallerArgs += @("--target", "codex")
    }
}

if (-not $HasMode) {
    if ($PromptMode -and (Test-CanPrompt)) {
        Select-RuntimeMode
        $InstallerArgs += @("--mode", $SelectedMode)
        if ($SelectedMode -eq "rest") {
            $env:PAM_OS_REST_URL = $RestUrl
            $env:PAM_OS_REST_USERNAME = $RestUsername
            $env:PAM_OS_REST_PASSWORD = $RestPassword
        }
    }
}

if ($AssumeYes) {
    $InstallerArgs += "--yes"
}

$FinalArgs = @()
$FinalArgs += $InstallerArgs
$FinalArgs += $Passthrough

& $Installer @FinalArgs
exit $LASTEXITCODE
