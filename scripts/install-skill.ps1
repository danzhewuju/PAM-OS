#requires -Version 5.1

$ErrorActionPreference = "Stop"
$CliArgs = $args

function Get-EnvOrDefault {
    param(
        [string]$Name,
        [string]$Default
    )
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value
}

function Join-PathMany {
    param([string[]]$Parts)
    $path = $Parts[0]
    for ($i = 1; $i -lt $Parts.Count; $i++) {
        $path = Join-Path $path $Parts[$i]
    }
    return $path
}

$SkillName = Get-EnvOrDefault "PAM_OS_SKILL_NAME" "pam-os-memory"
$DefaultRepoUrl = Get-EnvOrDefault "PAM_OS_REPO_URL" "https://github.com/danzhewuju/PAM-OS.git"
$DefaultRepoRef = Get-EnvOrDefault "PAM_OS_REPO_REF" "master"
$HomeDir = $HOME
$AppDataDir = Get-EnvOrDefault "APPDATA" (Join-PathMany @($HomeDir, "AppData", "Roaming"))
$LocalAppDataDir = Get-EnvOrDefault "LOCALAPPDATA" (Join-PathMany @($HomeDir, "AppData", "Local"))
$DefaultRepoDir = Get-EnvOrDefault "PAM_OS_REPO_DIR" (Join-PathMany @($LocalAppDataDir, "pam-os", "repo"))
$DefaultDbPath = Get-EnvOrDefault "PAM_OS_DB" (Get-EnvOrDefault "PAM_OS_DB_PATH" (Join-PathMany @($HomeDir, ".pam-os", "memory.sqlite3")))

$CodexHome = Get-EnvOrDefault "CODEX_HOME" (Join-Path $HomeDir ".codex")
$CodexDefaultDir = Join-PathMany @($CodexHome, "skills", $SkillName)
$ClaudeDefaultDir = Join-PathMany @($HomeDir, ".claude", "skills", $SkillName)
$OpenCodeConfigDir = Join-Path $AppDataDir "opencode"
$OpenCodeAgentsFile = Join-Path $OpenCodeConfigDir "AGENTS.md"
$CcSwitchHome = Get-EnvOrDefault "CC_SWITCH_HOME" (Join-Path $AppDataDir "cc-switch")
$CcSwitchDefaultDir = Join-PathMany @($CcSwitchHome, "skills", $SkillName)

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { "" }
$WorkDir = (Get-Location).Path
$TempDir = ""

function Write-Info {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Blue
}

function Write-Warn {
    param([string]$Message)
    Write-Warning $Message
}

function Stop-Install {
    param([string]$Message)
    Write-Error "error: $Message"
    exit 1
}

function Show-Usage {
    @"
PAM-OS skill installer for Windows

Usage:
  .\scripts\install-skill.ps1 [options]

Options:
  --all                 Install Codex, Claude Code, OpenCode, and CC Switch targets.
  --codex               Install the Codex global skill.
  --claude              Install the Claude Code global skill.
  --opencode            Install OpenCode compatibility.
  --cc-switch           Install the CC Switch export bundle.
  --mode cli|rest       Set skill runtime mode. Default: prompt, then cli.
  --no-init             Skip running "memory init" after CLI-mode install.
  --python VERSION      Python version for uv run --python. Default: 3.12.
  --cli-command COMMAND PAM-OS CLI command. Default: memory.
  --repo-dir DIR        PAM-OS repo used for CLI mode. Default: $DefaultRepoDir.
  --db PATH             PAM-OS SQLite database path. Default: $DefaultDbPath.
  --repo-url URL        Git repository used when the skill template is not local.
  --ref REF             Git ref used when downloading/cloning. Default: master.
  --source DIR          Use an existing pam-os-memory skill directory.
  --yes                 Accept safe defaults and replace existing installs.
  --non-interactive     Same as --yes.
  -h, --help            Show this help.

Environment:
  PAM_OS_REPO_URL       Default repo URL. Current default: $DefaultRepoUrl
  PAM_OS_REPO_REF       Default repo ref. Current default: $DefaultRepoRef
  PAM_OS_REPO_DIR       Default CLI repo dir. Current default: $DefaultRepoDir
  PAM_OS_DB             Default database path. Current default: $DefaultDbPath
  PAM_OS_CLI_PYTHON     Default CLI Python version. Default: 3.12
  PAM_OS_CLI_COMMAND    Default CLI command. Default: memory
  CODEX_HOME            Codex home. Default: $CodexHome
  CC_SWITCH_HOME        CC Switch home. Default: $CcSwitchHome

Without a target option, the installer prompts for targets. With --yes and no
target option, it installs Codex only.
"@
}

function Test-CanPrompt {
    return [Environment]::UserInteractive
}

function Read-User {
    param([string]$Prompt)
    if (-not (Test-CanPrompt)) {
        Stop-Install "Interactive prompt requires a user session. Re-run with --yes or explicit options."
    }
    return Read-Host $Prompt
}

function Confirm-Action {
    param(
        [string]$Prompt,
        [string]$Default = "y"
    )
    if ($script:AssumeYes) {
        return $Default -eq "y"
    }

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

function Prompt-Value {
    param(
        [string]$Prompt,
        [string]$Default
    )
    if ($script:AssumeYes) {
        return $Default
    }
    $reply = Read-User "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($reply)) {
        return $Default
    }
    return $reply
}

function Prompt-Secret {
    param([string]$Prompt)
    if ($script:AssumeYes) {
        return ""
    }

    $secure = Read-Host "$Prompt (leave empty for none)" -AsSecureString
    if ($secure.Length -eq 0) {
        return ""
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
    Write-Host "  1) codex      - Codex global skill ($CodexDefaultDir)"
    Write-Host "  2) claude     - Claude Code global skill ($ClaudeDefaultDir)"
    Write-Host "  3) opencode   - OpenCode compatibility"
    Write-Host "  4) cc-switch  - CC Switch export bundle ($CcSwitchDefaultDir)"
    Write-Host "  5) all"
    Write-Host ""
    Write-Host "Select one or more targets, separated by commas or spaces."

    while ($true) {
        $selection = Read-User "Selection [1]"
        if ([string]::IsNullOrWhiteSpace($selection)) {
            $selection = "1"
        }

        $script:InstallCodex = $false
        $script:InstallClaude = $false
        $script:InstallOpenCode = $false
        $script:InstallCcSwitch = $false
        $valid = $true

        foreach ($item in ($selection -replace ",", " " -split "\s+" | Where-Object { $_ })) {
            switch -Regex ($item) {
                "^(1|codex)$" { $script:InstallCodex = $true; continue }
                "^(2|claude|claude-code)$" { $script:InstallClaude = $true; continue }
                "^(3|opencode)$" { $script:InstallOpenCode = $true; continue }
                "^(4|cc-switch|cc_switch)$" { $script:InstallCcSwitch = $true; continue }
                "^(5|all)$" {
                    $script:InstallCodex = $true
                    $script:InstallClaude = $true
                    $script:InstallOpenCode = $true
                    $script:InstallCcSwitch = $true
                    continue
                }
                default {
                    Write-Warn "Unknown target: $item"
                    $valid = $false
                    break
                }
            }
        }

        if ($valid -and ($script:InstallCodex -or $script:InstallClaude -or $script:InstallOpenCode -or $script:InstallCcSwitch)) {
            return
        }

        Write-Host "Please select at least one valid target."
    }
}

function Get-Timestamp {
    return (Get-Date).ToString("yyyyMMdd-HHmmss")
}

function Resolve-AbsolutePath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }
    $expanded = [Environment]::ExpandEnvironmentVariables($Path)
    $full = [IO.Path]::GetFullPath($expanded)
    return $full
}

function ConvertTo-TomlString {
    param([string]$Value)
    if ($null -eq $Value) {
        $Value = ""
    }
    return ($Value -replace "\\", "\\" -replace '"', '\"')
}

function Test-PamRepo {
    param([string]$Path)
    return (
        -not [string]::IsNullOrWhiteSpace($Path) -and
        (Test-Path -LiteralPath (Join-Path $Path "pyproject.toml") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-PathMany @($Path, "src", "pam_os")) -PathType Container)
    )
}

function Ensure-CliRepo {
    if ($script:InstallMode -ne "cli") {
        return
    }

    if ((-not [string]::IsNullOrWhiteSpace($script:CliRepoDir)) -and (Test-Path -LiteralPath (Join-Path $script:CliRepoDir "pyproject.toml") -PathType Leaf)) {
        $script:CliRepoDir = Resolve-AbsolutePath $script:CliRepoDir
        return
    }

    if (Test-PamRepo $WorkDir) {
        $script:CliRepoDir = Resolve-AbsolutePath $WorkDir
        return
    }

    if ($ScriptDir) {
        $scriptParent = Resolve-AbsolutePath (Join-Path $ScriptDir "..")
        if (Test-PamRepo $scriptParent) {
            $script:CliRepoDir = $scriptParent
            return
        }
    }

    if ([string]::IsNullOrWhiteSpace($script:CliRepoDir)) {
        $script:CliRepoDir = $DefaultRepoDir
    }

    if (Test-Path -LiteralPath (Join-Path $script:CliRepoDir "pyproject.toml") -PathType Leaf) {
        $script:CliRepoDir = Resolve-AbsolutePath $script:CliRepoDir
        return
    }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Stop-Install "Could not find a PAM-OS repo for CLI mode and git is not installed."
    }

    Write-Info "Fetching PAM-OS CLI repo into $($script:CliRepoDir)"
    $parent = Split-Path -Parent $script:CliRepoDir
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    & git clone --depth 1 --branch $script:RepoRef $script:RepoUrl $script:CliRepoDir | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Branch clone failed; trying default branch."
        & git clone --depth 1 $script:RepoUrl $script:CliRepoDir | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Stop-Install "Could not clone $($script:RepoUrl)"
        }
    }
}

function Copy-Directory {
    param(
        [string]$Source,
        [string]$Destination
    )
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function Invoke-CliInit {
    if ($script:InstallMode -ne "cli" -or -not $script:RunInit) {
        return
    }

    if (-not (Confirm-Action "Initialize PAM-OS memory database with `"$($script:CliCommand) init`"?" "y")) {
        Write-Warn "Skipped PAM-OS memory database init."
        return
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Warn "Could not run init because uv is not installed or not on PATH."
        Write-Warn "Run manually later: uv --directory $($script:CliRepoDir) run --python $($script:CliPython) $($script:CliCommand) --db $($script:DbPath) init"
        return
    }

    Write-Info "Initializing PAM-OS memory database"
    & uv --directory $script:CliRepoDir run --python $script:CliPython $script:CliCommand --db $script:DbPath init
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "PAM-OS memory database init failed."
        Write-Warn "Run manually later: uv --directory $($script:CliRepoDir) run --python $($script:CliPython) $($script:CliCommand) --db $($script:DbPath) init"
    }
}

function Prepare-Destination {
    param([string]$Destination)

    if (-not (Test-Path -LiteralPath $Destination)) {
        return $true
    }

    if (-not $script:AssumeYes) {
        Write-Host ""
        Write-Host "Existing installation found:"
        Write-Host "  $Destination"
        Write-Host "Choose what to do:"
        Write-Host "  1) replace existing install"
        Write-Host "  2) skip this target"
        Write-Host "  3) abort"
        $choice = Read-User "Selection [1]"
        if ([string]::IsNullOrWhiteSpace($choice)) {
            $choice = "1"
        }
        switch ($choice) {
            "1" {}
            "2" { return $false }
            "3" { Stop-Install "Aborted by user." }
            default { Stop-Install "Invalid selection: $choice" }
        }
    }

    $resolved = Resolve-AbsolutePath $Destination
    Write-Info "Replacing existing install: $resolved"
    Remove-Item -LiteralPath $resolved -Recurse -Force
    return $true
}

function Install-SkillDir {
    param(
        [string]$Source,
        [string]$Destination,
        [string]$Label
    )

    if (-not (Prepare-Destination $Destination)) {
        Write-Warn "Skipped $Label."
        return
    }

    Write-Info "Installing $Label"
    Copy-Directory $Source $Destination
    Write-SkillConfig (Join-Path $Destination "config.toml")
    Write-Host "Installed: $Destination"
}

function Find-SkillSource {
    $roots = @()
    if (-not [string]::IsNullOrWhiteSpace($script:SourceDir)) {
        $roots += $script:SourceDir
    }
    $roots += Join-PathMany @($WorkDir, "skills", $SkillName)
    $roots += Join-PathMany @($WorkDir, ".agents", "skills", $SkillName)
    $roots += Join-PathMany @($WorkDir, ".claude", "skills", $SkillName)

    if ($ScriptDir) {
        $roots += Join-PathMany @($ScriptDir, "..", "skills", $SkillName)
        $roots += Join-PathMany @($ScriptDir, "..", ".agents", "skills", $SkillName)
        $roots += Join-PathMany @($ScriptDir, "..", ".claude", "skills", $SkillName)
        $roots += Join-PathMany @($ScriptDir, ".agents", "skills", $SkillName)
        $roots += Join-PathMany @($ScriptDir, ".claude", "skills", $SkillName)
    }

    foreach ($candidate in $roots) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $skillFile = Join-Path $candidate "SKILL.md"
            if (Test-Path -LiteralPath $skillFile -PathType Leaf) {
                return Resolve-AbsolutePath $candidate
            }
        }
    }

    return ""
}

function Download-RepoSource {
    param(
        [string]$RepoUrl,
        [string]$Ref
    )

    $script:TempDir = Join-Path ([IO.Path]::GetTempPath()) ("pam-os-skill." + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $script:TempDir | Out-Null
    $repoDir = Join-Path $script:TempDir "repo"

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Stop-Install "Could not find a local skill template and git is not installed. Re-run from a PAM-OS checkout or install git."
    }

    Write-Info "Fetching PAM-OS skill template from $RepoUrl ($Ref)"
    & git clone --depth 1 --branch $Ref $RepoUrl $repoDir | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Branch clone failed; trying default branch."
        & git clone --depth 1 $RepoUrl $repoDir | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Stop-Install "Could not clone $RepoUrl"
        }
    }

    $candidates = @(
        Join-PathMany @($repoDir, "skills", $SkillName),
        Join-PathMany @($repoDir, ".agents", "skills", $SkillName),
        Join-PathMany @($repoDir, ".claude", "skills", $SkillName)
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate "SKILL.md") -PathType Leaf) {
            return $candidate
        }
    }

    Stop-Install "Downloaded repository does not contain $SkillName."
}

function Write-SkillConfig {
    param([string]$Path)

    $escapedUrl = ConvertTo-TomlString $script:RestUrl
    $escapedUser = ConvertTo-TomlString $script:RestUsername
    $escapedPass = ConvertTo-TomlString $script:RestPassword
    $escapedPython = ConvertTo-TomlString $script:CliPython
    $escapedCommand = ConvertTo-TomlString $script:CliCommand
    $escapedRepoDir = ConvertTo-TomlString $script:CliRepoDir
    $escapedDbPath = ConvertTo-TomlString $script:DbPath

    $content = @"
# PAM-OS skill runtime mode.
# Default is CLI. Change mode to "rest" when the REST server is running.

mode = "$($script:InstallMode)"

[cli]
python = "$escapedPython"
command = "$escapedCommand"
repo_dir = "$escapedRepoDir"
db_path = "$escapedDbPath"

[rest]
url = "$escapedUrl"
username = "$escapedUser"
password = "$escapedPass"
"@
    Set-Content -LiteralPath $Path -Value $content -Encoding UTF8
}

function Update-ManagedBlock {
    param([string]$File)

    $start = "<!-- PAM-OS memory skill: begin -->"
    $end = "<!-- PAM-OS memory skill: end -->"

    $parent = Split-Path -Parent $File
    New-Item -ItemType Directory -Force -Path $parent | Out-Null

    if (Test-Path -LiteralPath $File -PathType Leaf) {
        $backup = "$File.bak.$(Get-Timestamp)"
        Write-Info "Backing up $File -> $backup"
        Copy-Item -LiteralPath $File -Destination $backup -Force
        $lines = Get-Content -LiteralPath $File
    }
    else {
        $lines = @()
    }

    $output = New-Object System.Collections.Generic.List[string]
    $skip = $false
    foreach ($line in $lines) {
        if ($line -eq $start) {
            $skip = $true
            continue
        }
        if ($line -eq $end) {
            $skip = $false
            continue
        }
        if (-not $skip) {
            $output.Add($line)
        }
    }

    while ($output.Count -gt 0 -and [string]::IsNullOrWhiteSpace($output[$output.Count - 1])) {
        $output.RemoveAt($output.Count - 1)
    }
    if ($output.Count -gt 0) {
        $output.Add("")
    }

    $output.Add($start)
    $output.Add("## PAM-OS Memory")
    $output.Add("")
    $output.Add("Use PAM-OS as local long-term memory when a task depends on user preferences, project history, prior decisions, long-term goals, answer style, or an explicit request to remember something.")
    $output.Add("")
    $output.Add("If the pam-os-memory skill is available, use it. Otherwise read the installed skill instructions from ``$ClaudeDefaultDir\SKILL.md``.")
    $output.Add("")
    $output.Add("Do not store secrets or sensitive details unless the user explicitly asks to remember them.")
    $output.Add($end)

    Set-Content -LiteralPath $File -Value $output -Encoding UTF8
}

function Install-OpenCode {
    param([string]$Source)

    Write-Info "Installing OpenCode compatibility"
    if ($script:InstallClaude) {
        Write-Info "Claude-compatible skill target is already handled by the Claude Code install."
    }
    else {
        Install-SkillDir $Source $ClaudeDefaultDir "OpenCode Claude-compatible skill (~\.claude\skills)"
    }

    if (Confirm-Action "Add/update PAM-OS guidance in $OpenCodeAgentsFile?" "y") {
        Update-ManagedBlock $OpenCodeAgentsFile
        Write-Host "Updated: $OpenCodeAgentsFile"
    }
    else {
        Write-Warn "Skipped OpenCode AGENTS.md guidance."
    }
}

function Show-Summary {
    if ($script:InstallMode -eq "cli") {
        $cliSummary = "  CLI command: uv --directory $($script:CliRepoDir) run --python $($script:CliPython) $($script:CliCommand) --db $($script:DbPath) prepare `"<task>`" --json"
        $restSummary = ""
    }
    else {
        $cliSummary = ""
        $restSummary = "  REST URL:    $($script:RestUrl)"
    }

    @"

Done.

Next checks:
  Codex:       restart Codex, then ask "List available skills" or "Use `$pam-os-memory."
  Claude Code: run "claude" and ask "List available skills" or invoke "/pam-os-memory".
  OpenCode:    restart opencode; it can read $OpenCodeAgentsFile and Claude-compatible skills.
  CC Switch:   import or point CC Switch to the installed bundle directory if its UI asks for a skill path.

PAM-OS runtime:
  mode:        $($script:InstallMode)
$cliSummary
$restSummary

"@ | Write-Host
}

try {
    $script:AssumeYes = $false
    $script:InstallCodex = $false
    $script:InstallClaude = $false
    $script:InstallOpenCode = $false
    $script:InstallCcSwitch = $false
    $script:ModeArg = ""
    $script:RepoUrl = $DefaultRepoUrl
    $script:RepoRef = $DefaultRepoRef
    $script:CliRepoDir = $DefaultRepoDir
    $script:CliPython = Get-EnvOrDefault "PAM_OS_CLI_PYTHON" "3.12"
    $script:CliCommand = Get-EnvOrDefault "PAM_OS_CLI_COMMAND" "memory"
    $script:DbPath = $DefaultDbPath
    $script:SourceDir = ""
    $script:RunInit = $true

    for ($i = 0; $i -lt $CliArgs.Count; $i++) {
        $arg = $CliArgs[$i]
        switch ($arg) {
            "--all" {
                $script:InstallCodex = $true
                $script:InstallClaude = $true
                $script:InstallOpenCode = $true
                $script:InstallCcSwitch = $true
            }
            "--codex" { $script:InstallCodex = $true }
            "--claude" { $script:InstallClaude = $true }
            "--opencode" { $script:InstallOpenCode = $true }
            "--cc-switch" { $script:InstallCcSwitch = $true }
            "--mode" {
                $i++
                $script:ModeArg = if ($i -lt $CliArgs.Count) { $CliArgs[$i] } else { "" }
            }
            "--no-init" { $script:RunInit = $false }
            "--python" {
                $i++
                $script:CliPython = if ($i -lt $CliArgs.Count) { $CliArgs[$i] } else { "" }
            }
            "--cli-command" {
                $i++
                $script:CliCommand = if ($i -lt $CliArgs.Count) { $CliArgs[$i] } else { "" }
            }
            "--repo-dir" {
                $i++
                $script:CliRepoDir = if ($i -lt $CliArgs.Count) { $CliArgs[$i] } else { "" }
            }
            "--db" {
                $i++
                $script:DbPath = if ($i -lt $CliArgs.Count) { $CliArgs[$i] } else { "" }
            }
            "--repo-url" {
                $i++
                $script:RepoUrl = if ($i -lt $CliArgs.Count) { $CliArgs[$i] } else { "" }
            }
            "--ref" {
                $i++
                $script:RepoRef = if ($i -lt $CliArgs.Count) { $CliArgs[$i] } else { "" }
            }
            "--source" {
                $i++
                $script:SourceDir = if ($i -lt $CliArgs.Count) { $CliArgs[$i] } else { "" }
            }
            "--yes" { $script:AssumeYes = $true }
            "--non-interactive" { $script:AssumeYes = $true }
            "-h" {
                Show-Usage
                exit 0
            }
            "--help" {
                Show-Usage
                exit 0
            }
            default {
                Stop-Install "Unknown option: $arg"
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($script:ModeArg) -and $script:ModeArg -notin @("cli", "rest")) {
        Stop-Install "--mode must be cli or rest."
    }
    if ([string]::IsNullOrWhiteSpace($script:CliPython)) {
        Stop-Install "--python must not be empty."
    }
    if ([string]::IsNullOrWhiteSpace($script:CliCommand)) {
        Stop-Install "--cli-command must not be empty."
    }
    if ([string]::IsNullOrWhiteSpace($script:RepoUrl)) {
        Stop-Install "--repo-url must not be empty."
    }
    if ([string]::IsNullOrWhiteSpace($script:RepoRef)) {
        Stop-Install "--ref must not be empty."
    }
    if ([string]::IsNullOrWhiteSpace($script:DbPath)) {
        Stop-Install "--db must not be empty."
    }

    if (-not $script:AssumeYes -and -not (Test-CanPrompt)) {
        Stop-Install "Interactive install requires a user session. Use --yes with explicit options for non-interactive installs."
    }

    Write-Info "PAM-OS global skill installer"

    if (-not ($script:InstallCodex -or $script:InstallClaude -or $script:InstallOpenCode -or $script:InstallCcSwitch)) {
        if ($script:AssumeYes) {
            $script:InstallCodex = $true
        }
        else {
            Select-InstallTargets
        }
    }

    if (-not ($script:InstallCodex -or $script:InstallClaude -or $script:InstallOpenCode -or $script:InstallCcSwitch)) {
        Stop-Install "No install targets selected."
    }

    if ([string]::IsNullOrWhiteSpace($script:ModeArg)) {
        if ($script:AssumeYes) {
            $script:InstallMode = "cli"
        }
        else {
            Write-Host ""
            Write-Host "Runtime mode:"
            Write-Host "  1) cli  - no long-running server; model runs the local memory CLI"
            Write-Host "  2) rest - model calls a running PAM-OS REST server"
            $modeChoice = Read-User "Selection [1]"
            if ([string]::IsNullOrWhiteSpace($modeChoice)) {
                $modeChoice = "1"
            }
            switch ($modeChoice) {
                "1" { $script:InstallMode = "cli" }
                "cli" { $script:InstallMode = "cli" }
                "2" { $script:InstallMode = "rest" }
                "rest" { $script:InstallMode = "rest" }
                default { Stop-Install "Invalid runtime mode: $modeChoice" }
            }
        }
    }
    else {
        $script:InstallMode = $script:ModeArg
    }

    $script:RestUrl = "http://127.0.0.1:8765"
    $script:RestUsername = ""
    $script:RestPassword = ""

    if ($script:InstallMode -eq "rest") {
        $script:RestUrl = Prompt-Value "PAM-OS REST URL" $script:RestUrl
        if (Confirm-Action "Configure REST Basic Auth credentials in skill config?" "n") {
            $script:RestUsername = Prompt-Value "REST username" ""
            $script:RestPassword = Prompt-Secret "REST password"
        }
    }

    Ensure-CliRepo

    $skillSource = Find-SkillSource
    if ([string]::IsNullOrWhiteSpace($skillSource)) {
        $skillSource = Download-RepoSource $script:RepoUrl $script:RepoRef
    }

    if (-not (Test-Path -LiteralPath (Join-Path $skillSource "SKILL.md") -PathType Leaf)) {
        Stop-Install "Skill source is invalid: $skillSource"
    }
    Write-Info "Using skill template: $skillSource"

    if ($script:InstallCodex) {
        Install-SkillDir $skillSource $CodexDefaultDir "Codex global skill"
    }

    if ($script:InstallClaude) {
        Install-SkillDir $skillSource $ClaudeDefaultDir "Claude Code global skill"
    }

    if ($script:InstallOpenCode) {
        Install-OpenCode $skillSource
    }

    if ($script:InstallCcSwitch) {
        Install-SkillDir $skillSource $CcSwitchDefaultDir "CC Switch export bundle"
    }

    Invoke-CliInit
    Show-Summary
}
finally {
    if (-not [string]::IsNullOrWhiteSpace($TempDir) -and (Test-Path -LiteralPath $TempDir -PathType Container)) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force
    }
}
