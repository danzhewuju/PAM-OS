#requires -Version 5.1

$ErrorActionPreference = "Stop"
$CliArgs = $args

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $ScriptDir ".."))
$Installer = Join-Path $RepoRoot "scripts\install-plugin.ps1"
$PluginName = if ([string]::IsNullOrWhiteSpace($env:PAM_OS_PLUGIN_NAME)) { "pam-os-memory" } else { $env:PAM_OS_PLUGIN_NAME }
$SourceDir = Join-Path (Join-Path $RepoRoot "plugins") $PluginName
$HomeDir = $HOME
$CodexHome = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) { Join-Path $HomeDir ".codex" } else { $env:CODEX_HOME }
$HermesHome = if ([string]::IsNullOrWhiteSpace($env:HERMES_HOME)) { Join-Path $HomeDir ".hermes" } else { $env:HERMES_HOME }
$CodexSkillDir = Join-Path (Join-Path $CodexHome "skills") $PluginName
$ClaudeSkillDir = Join-Path (Join-Path (Join-Path $HomeDir ".claude") "skills") $PluginName
$HermesSkillDir = Join-Path (Join-Path $HermesHome "skills") $PluginName

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
$RestUrlExplicit = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("PAM_OS_REST_URL"))
$RestUsernameExplicit = $null -ne [Environment]::GetEnvironmentVariable("PAM_OS_REST_USERNAME")
$RestPasswordExplicit = $null -ne [Environment]::GetEnvironmentVariable("PAM_OS_REST_PASSWORD")

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

function ConvertFrom-TomlBasicString {
    param([string]$Value)

    if ($null -eq $Value) {
        return ""
    }

    $builder = New-Object System.Text.StringBuilder
    $escaped = $false
    foreach ($ch in $Value.ToCharArray()) {
        if ($escaped) {
            switch ([string]$ch) {
                '"' { [void]$builder.Append('"') }
                "\" { [void]$builder.Append("\") }
                "n" { [void]$builder.Append("`n") }
                "r" { [void]$builder.Append("`r") }
                "t" { [void]$builder.Append("`t") }
                default { [void]$builder.Append($ch) }
            }
            $escaped = $false
            continue
        }

        if ([string]$ch -eq "\") {
            $escaped = $true
            continue
        }
        [void]$builder.Append($ch)
    }

    if ($escaped) {
        [void]$builder.Append("\")
    }
    return $builder.ToString()
}

function Get-TomlStringValue {
    param(
        [string]$Text,
        [string]$Key,
        [string]$Section = ""
    )

    $scope = $Text
    if (-not [string]::IsNullOrWhiteSpace($Section)) {
        $sectionPattern = "(?ms)^\s*\[$([regex]::Escape($Section))\]\s*(.*?)(?=^\s*\[|\z)"
        $sectionMatch = [regex]::Match($Text, $sectionPattern)
        if (-not $sectionMatch.Success) {
            return ""
        }
        $scope = $sectionMatch.Groups[1].Value
    }

    $keyPattern = '(?m)^\s*' + [regex]::Escape($Key) + '\s*=\s*"((?:\\.|[^"])*)"\s*$'
    $match = [regex]::Match($scope, $keyPattern)
    if (-not $match.Success) {
        return ""
    }
    return ConvertFrom-TomlBasicString $match.Groups[1].Value
}

function Add-RestConfigPath {
    param(
        [System.Collections.Generic.List[string]]$Paths,
        [System.Collections.Generic.HashSet[string]]$Seen,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    $key = $Path.ToLowerInvariant()
    if ($Seen.Add($key)) {
        $Paths.Add($Path)
    }
}

function Get-RestConfigSearchPaths {
    $paths = New-Object System.Collections.Generic.List[string]
    $seen = New-Object System.Collections.Generic.HashSet[string]

    if ($SelectedTargets.Count -gt 0) {
        foreach ($target in $SelectedTargets) {
            switch ($target) {
                "codex" { Add-RestConfigPath $paths $seen (Join-Path $CodexSkillDir "config.toml") }
                "claude" { Add-RestConfigPath $paths $seen (Join-Path $ClaudeSkillDir "config.toml") }
                "opencode" { Add-RestConfigPath $paths $seen (Join-Path $ClaudeSkillDir "config.toml") }
                "hermes" { Add-RestConfigPath $paths $seen (Join-Path $HermesSkillDir "config.toml") }
                "all" {
                    Add-RestConfigPath $paths $seen (Join-Path $CodexSkillDir "config.toml")
                    Add-RestConfigPath $paths $seen (Join-Path $ClaudeSkillDir "config.toml")
                    Add-RestConfigPath $paths $seen (Join-Path $HermesSkillDir "config.toml")
                }
            }
        }
    }

    Add-RestConfigPath $paths $seen (Join-Path $CodexSkillDir "config.toml")
    Add-RestConfigPath $paths $seen (Join-Path $ClaudeSkillDir "config.toml")
    Add-RestConfigPath $paths $seen (Join-Path $HermesSkillDir "config.toml")
    return @($paths)
}

function Find-ExistingRestConfig {
    foreach ($rawPath in (Get-RestConfigSearchPaths)) {
        $path = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($rawPath))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            continue
        }

        try {
            $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
            $mode = Get-TomlStringValue $text "mode"
            if ($mode.Trim().ToLowerInvariant() -ne "rest") {
                continue
            }

            $url = Get-TomlStringValue $text "url" "rest"
            if ([string]::IsNullOrWhiteSpace($url)) {
                continue
            }

            return [pscustomobject]@{
                Path = $path
                Mode = $mode
                Url = $url
                Username = Get-TomlStringValue $text "username" "rest"
                Password = Get-TomlStringValue $text "password" "rest"
            }
        }
        catch {
            continue
        }
    }

    return $null
}

function Show-RestConfigSummary {
    param(
        [string]$Path,
        [string]$Mode,
        [string]$Url,
        [string]$Username,
        [string]$Password
    )

    $passwordLabel = if ([string]::IsNullOrEmpty($Password)) { "empty" } else { "set" }
    Write-Host ""
    Write-Host "REST configuration found:"
    Write-Host "  path: $Path"
    if (-not [string]::IsNullOrWhiteSpace($Mode)) {
        Write-Host "  mode: $Mode"
    }
    Write-Host "  url: $Url"
    Write-Host "  username: $(if ([string]::IsNullOrEmpty($Username)) { '<empty>' } else { $Username })"
    Write-Host "  password: $passwordLabel"
}

function Confirm-User {
    param(
        [string]$Prompt,
        [string]$Default = "y"
    )

    $suffix = if ($Default -eq "y") { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $reply = Read-User "$Prompt $suffix"
        if ([string]::IsNullOrWhiteSpace($reply)) {
            $reply = $Default
        }
        switch -Regex ($reply) {
            "^(y|yes)$" { return $true }
            "^(n|no)$" { return $false }
            default { Write-Host "Please answer y or n." }
        }
    }
}

function Configure-RestRuntime {
    $explicitCount = 0
    if ($RestUrlExplicit) { $explicitCount++ }
    if ($RestUsernameExplicit) { $explicitCount++ }
    if ($RestPasswordExplicit) { $explicitCount++ }

    if ($explicitCount -eq 0) {
        $existing = Find-ExistingRestConfig
        if ($null -ne $existing) {
            Show-RestConfigSummary $existing.Path $existing.Mode $existing.Url $existing.Username $existing.Password
            if (Confirm-User "Use this existing REST configuration?" "y") {
                $script:RestUrl = $existing.Url
                $script:RestUsername = $existing.Username
                $script:RestPassword = $existing.Password
                return
            }
        }
    }

    if ($explicitCount -gt 0) {
        Show-RestConfigSummary "options/environment" "" $RestUrl $RestUsername $RestPassword
        if (Confirm-User "Use this REST configuration?" "y") {
            return
        }
    }

    $script:RestUrl = Prompt-Value "PAM-OS REST URL" $RestUrl
    $script:RestUsername = Prompt-Value "REST username" $RestUsername
    $script:RestPassword = Prompt-Secret "REST password" $RestPassword
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
                Configure-RestRuntime
                if ([string]::IsNullOrWhiteSpace($script:RestUrl)) {
                    Stop-LocalInstall "REST URL must not be empty."
                }
                return
            }
            "rest" {
                $script:SelectedMode = "rest"
                Configure-RestRuntime
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
  In interactive REST mode, existing installed skill REST settings are offered for reuse.
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
            $RestUrlExplicit = $true
            $RestUrl = $CliArgs[$i + 1]
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--rest-username" {
            if ($i + 1 -ge $CliArgs.Count -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--rest-username requires a value"
            }
            $RestUsernameExplicit = $true
            $RestUsername = $CliArgs[$i + 1]
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--rest-user" {
            if ($i + 1 -ge $CliArgs.Count -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--rest-user requires a value"
            }
            $RestUsernameExplicit = $true
            $RestUsername = $CliArgs[$i + 1]
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--rest-password" {
            if ($i + 1 -ge $CliArgs.Count -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--rest-password requires a value"
            }
            $RestPasswordExplicit = $true
            $RestPassword = $CliArgs[$i + 1]
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--codex-skill-dir" {
            if ($i + 1 -ge $CliArgs.Count -or [string]::IsNullOrWhiteSpace($CliArgs[$i + 1]) -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--codex-skill-dir requires a value"
            }
            $CodexSkillDir = $CliArgs[$i + 1]
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--claude-skill-dir" {
            if ($i + 1 -ge $CliArgs.Count -or [string]::IsNullOrWhiteSpace($CliArgs[$i + 1]) -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--claude-skill-dir requires a value"
            }
            $ClaudeSkillDir = $CliArgs[$i + 1]
            $Passthrough += $arg
            $i++
            $Passthrough += $CliArgs[$i]
        }
        "--hermes-skill-dir" {
            if ($i + 1 -ge $CliArgs.Count -or [string]::IsNullOrWhiteSpace($CliArgs[$i + 1]) -or $CliArgs[$i + 1].StartsWith("-")) {
                Stop-LocalInstall "--hermes-skill-dir requires a value"
            }
            $HermesSkillDir = $CliArgs[$i + 1]
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
