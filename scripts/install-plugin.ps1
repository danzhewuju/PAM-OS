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

$PluginName = Get-EnvOrDefault "PAM_OS_PLUGIN_NAME" "pam-os-memory"
$McpServerName = "pam_os_memory"
$DefaultRepoUrl = Get-EnvOrDefault "PAM_OS_REPO_URL" "https://github.com/danzhewuju/PAM-OS.git"
$DefaultRepoRef = Get-EnvOrDefault "PAM_OS_REPO_REF" "master"
$HomeDir = $HOME
$AppDataDir = Get-EnvOrDefault "APPDATA" (Join-PathMany @($HomeDir, "AppData", "Roaming"))
$LocalAppDataDir = Get-EnvOrDefault "LOCALAPPDATA" (Join-PathMany @($HomeDir, "AppData", "Local"))
$DefaultRepoDir = Get-EnvOrDefault "PAM_OS_REPO_DIR" (Join-PathMany @($LocalAppDataDir, "pam-os", "repo"))
$DefaultDbPath = Get-EnvOrDefault "PAM_OS_DB" (Get-EnvOrDefault "PAM_OS_DB_PATH" (Join-PathMany @($HomeDir, ".pam-os", "memory.sqlite3")))
$CodexHome = Get-EnvOrDefault "CODEX_HOME" (Join-Path $HomeDir ".codex")
$DefaultPluginDir = Join-PathMany @($HomeDir, "plugins", $PluginName)
$DefaultMarketplacePath = Join-PathMany @($HomeDir, ".agents", "plugins", "marketplace.json")
$DefaultCodexConfig = Join-Path $CodexHome "config.toml"
$DefaultCodexSkillDir = Join-PathMany @($CodexHome, "skills", $PluginName)
$DefaultClaudeSkillDir = Join-PathMany @($HomeDir, ".claude", "skills", $PluginName)
$DefaultOpenCodeAgentsFile = Join-PathMany @($AppDataDir, "opencode", "AGENTS.md")
$HermesHome = Get-EnvOrDefault "HERMES_HOME" (Join-Path $HomeDir ".hermes")
$DefaultHermesConfig = Join-Path $HermesHome "config.yaml"
$DefaultHermesAgentsFile = Join-Path $HermesHome "AGENTS.md"

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { "" }
$WorkDir = (Get-Location).Path

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
PAM-OS plugin installer for Windows

Usage:
  .\scripts\install-plugin.ps1 [options]

Options:
  --target TARGET      Install target: codex, claude, opencode, hermes, or all. Can be repeated.
  --codex             Install the Codex plugin, global skill fallback, and MCP config.
  --claude            Install the Claude Code global skill.
  --opencode          Install OpenCode compatibility guidance and Claude-compatible skill.
  --hermes            Install Hermes MCP config and guidance.
  --all               Install all supported targets.
  --plugin-dir DIR    Destination plugin dir. Default: $DefaultPluginDir.
  --marketplace PATH  Personal marketplace path. Default: $DefaultMarketplacePath.
  --codex-config PATH Codex config.toml path. Default: $DefaultCodexConfig.
  --codex-skill-dir DIR
                      Codex global skill fallback dir. Default: $DefaultCodexSkillDir.
  --claude-skill-dir DIR
                      Claude Code skill dir. Default: $DefaultClaudeSkillDir.
  --opencode-agents PATH
                      OpenCode AGENTS.md path. Default: $DefaultOpenCodeAgentsFile.
  --hermes-config PATH
                      Hermes config.yaml path. Default: $DefaultHermesConfig.
  --hermes-agents PATH
                      Hermes AGENTS.md path. Default: $DefaultHermesAgentsFile.
  --repo-dir DIR      Use an existing PAM-OS repo for MCP/dev mode. Default: $DefaultRepoDir.
  --repo-url URL      Git repository used to refresh the managed repo. Default: $DefaultRepoUrl.
  --ref REF           Git ref used to refresh the managed repo. Default: master.
  --no-refresh        Do not fetch or clone the managed repo before installing.
  --db PATH           PAM-OS SQLite database path. Default: $DefaultDbPath.
  --python VERSION    Python version for uv run --python. Default: 3.12.
  --uv-bin PATH       uv executable path. Default: auto-detect; falls back to system Python when unavailable.
  --source DIR        Existing pam-os-memory plugin source directory for dev/local installs.
  --skip-marketplace  Do not create or update the personal plugin marketplace entry.
  --skip-mcp-config   Do not register the MCP server in Codex config.toml.
  --skip-global-skill Do not install the Codex global skill fallback.
  --no-init           Skip running "memory init" after install.
  --yes               Accept safe defaults and replace existing installs.
  --non-interactive   Same as --yes.
  -h, --help          Show this help.

Without a target option, the installer prompts for targets. With --yes and no
target option, it installs Codex only.

The Codex target installs the plugin, writes a marketplace entry, installs the
global skill fallback, and registers a stdio MCP server in Codex config.toml.
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

function Select-InstallTargets {
    Write-Host ""
    Write-Host "Install targets:"
    Write-Host "  1) codex    - Codex plugin + MCP + global skill fallback"
    Write-Host "  2) claude   - Claude Code global skill"
    Write-Host "  3) opencode - OpenCode compatibility"
    Write-Host "  4) hermes   - Hermes MCP config and guidance"
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
        $script:InstallHermes = $false
        $valid = $true

        foreach ($item in ($selection -replace ",", " " -split "\s+" | Where-Object { $_ })) {
            switch -Regex ($item) {
                "^(1|codex)$" { $script:InstallCodex = $true; continue }
                "^(2|claude|claude-code)$" { $script:InstallClaude = $true; continue }
                "^(3|opencode)$" { $script:InstallOpenCode = $true; continue }
                "^(4|hermes)$" { $script:InstallHermes = $true; continue }
                "^(5|all)$" {
                    $script:InstallCodex = $true
                    $script:InstallClaude = $true
                    $script:InstallOpenCode = $true
                    $script:InstallHermes = $true
                    continue
                }
                default {
                    Write-Warn "Unknown target: $item"
                    $valid = $false
                    break
                }
            }
        }

        if ($valid -and ($script:InstallCodex -or $script:InstallClaude -or $script:InstallOpenCode -or $script:InstallHermes)) {
            return
        }
        Write-Host "Please select at least one valid target."
    }
}

function Enable-Target {
    param([string]$Target)
    switch ($Target) {
        "codex" { $script:InstallCodex = $true }
        "claude" { $script:InstallClaude = $true }
        "claude-code" { $script:InstallClaude = $true }
        "opencode" { $script:InstallOpenCode = $true }
        "hermes" { $script:InstallHermes = $true }
        "all" {
            $script:InstallCodex = $true
            $script:InstallClaude = $true
            $script:InstallOpenCode = $true
            $script:InstallHermes = $true
        }
        default { Stop-Install "Unknown target: $Target" }
    }
}

function Get-OptionValue {
    param(
        [string]$Option,
        [int]$Index
    )
    if ($Index -ge $CliArgs.Count -or [string]::IsNullOrWhiteSpace($CliArgs[$Index]) -or $CliArgs[$Index].StartsWith("-")) {
        Stop-Install "$Option requires a value"
    }
    return $CliArgs[$Index]
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
    return [IO.Path]::GetFullPath($expanded)
}

function ConvertTo-TomlString {
    param([string]$Value)
    if ($null -eq $Value) {
        $Value = ""
    }
    return ($Value -replace "\\", "\\" -replace '"', '\"')
}

function ConvertTo-JsonString {
    param([string]$Value)
    return $Value | ConvertTo-Json -Compress
}

function Test-PamRepo {
    param([string]$Path)
    return (
        -not [string]::IsNullOrWhiteSpace($Path) -and
        (Test-Path -LiteralPath (Join-Path $Path "pyproject.toml") -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-PathMany @($Path, "src", "pam_os")) -PathType Container)
    )
}

function Test-PluginSource {
    param([string]$Path)
    return (
        -not [string]::IsNullOrWhiteSpace($Path) -and
        (Test-Path -LiteralPath (Join-PathMany @($Path, ".codex-plugin", "plugin.json")) -PathType Leaf)
    )
}

function Test-SkillSource {
    param([string]$Path)
    return (
        -not [string]::IsNullOrWhiteSpace($Path) -and
        (Test-Path -LiteralPath (Join-Path $Path "SKILL.md") -PathType Leaf)
    )
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

function Prepare-Destination {
    param(
        [string]$Destination,
        [string]$Label
    )

    if (-not (Test-Path -LiteralPath $Destination)) {
        return $true
    }

    if (-not $script:AssumeYes) {
        Write-Host ""
        Write-Host "Existing $Label found:"
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
    Write-Info "Replacing existing ${Label}: $resolved"
    Remove-Item -LiteralPath $resolved -Recurse -Force
    return $true
}

function Find-UvBin {
    if (-not [string]::IsNullOrWhiteSpace($script:UvBin)) {
        $candidate = Resolve-AbsolutePath $script:UvBin
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
        Stop-Install "--uv-bin must point to an executable uv binary: $($script:UvBin)"
    }

    $envUv = Get-EnvOrDefault "PAM_OS_UV_BIN" ""
    if (-not [string]::IsNullOrWhiteSpace($envUv)) {
        $candidate = Resolve-AbsolutePath $envUv
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    foreach ($candidate in @(
        (Join-PathMany @($HomeDir, ".local", "bin", "uv.exe")),
        (Join-PathMany @($HomeDir, ".cargo", "bin", "uv.exe"))
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    return ""
}

function Find-PythonBin {
    foreach ($candidate in @("python", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            return $cmd.Source
        }
    }
    return ""
}

function Resolve-RepoDir {
    if ($script:RepoDirExplicit) {
        if (-not (Test-PamRepo $script:RepoDir)) {
            Stop-Install "--repo-dir is not a PAM-OS checkout: $($script:RepoDir)"
        }
        $script:RepoDir = Resolve-AbsolutePath $script:RepoDir
        return
    }

    if (Test-PamRepo $WorkDir) {
        $script:RepoDir = Resolve-AbsolutePath $WorkDir
        return
    }

    if ($ScriptDir) {
        $scriptParent = Resolve-AbsolutePath (Join-Path $ScriptDir "..")
        if (Test-PamRepo $scriptParent) {
            $script:RepoDir = $scriptParent
            return
        }
    }

    if ((Test-PamRepo $script:RepoDir) -and -not $script:RefreshRepo) {
        $script:RepoDir = Resolve-AbsolutePath $script:RepoDir
        return
    }

    if (-not $script:RefreshRepo) {
        Stop-Install "Could not find a PAM-OS repo. Run from a checkout or pass --repo-dir."
    }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Stop-Install "Could not refresh managed repo because git is not installed."
    }

    $script:RepoDir = Resolve-AbsolutePath $script:RepoDir
    if (Test-Path -LiteralPath $script:RepoDir -PathType Container) {
        Write-Info "Refreshing managed repo in $($script:RepoDir)"
        & git -C $script:RepoDir fetch --depth 1 origin $script:RepoRef | Out-Null
        if ($LASTEXITCODE -eq 0) {
            & git -C $script:RepoDir checkout FETCH_HEAD | Out-Null
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Could not refresh managed repo; using existing checkout if valid."
        }
        if (Test-PamRepo $script:RepoDir) {
            return
        }
    }

    Write-Info "Cloning managed repo into $($script:RepoDir)"
    $parent = Split-Path -Parent $script:RepoDir
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    & git clone --depth 1 --branch $script:RepoRef $script:RepoUrl $script:RepoDir | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Branch clone failed; trying default branch."
        & git clone --depth 1 $script:RepoUrl $script:RepoDir | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Stop-Install "Could not clone $($script:RepoUrl)"
        }
    }
}

function Find-PluginSource {
    $roots = @()
    if (-not [string]::IsNullOrWhiteSpace($script:SourceDir)) {
        $roots += $script:SourceDir
    }
    $roots += Join-PathMany @($script:RepoDir, "plugins", $PluginName)
    $roots += Join-PathMany @($WorkDir, "plugins", $PluginName)
    if ($ScriptDir) {
        $roots += Join-PathMany @($ScriptDir, "..", "plugins", $PluginName)
    }

    foreach ($candidate in $roots) {
        if (Test-PluginSource $candidate) {
            return Resolve-AbsolutePath $candidate
        }
    }
    return ""
}

function Find-SkillSource {
    $roots = @()
    if (-not [string]::IsNullOrWhiteSpace($script:SourceDir)) {
        $roots += Join-PathMany @($script:SourceDir, "skills", $PluginName)
        $roots += $script:SourceDir
    }
    $roots += Join-PathMany @($script:RepoDir, "skills", $PluginName)
    $roots += Join-PathMany @($script:RepoDir, "plugins", $PluginName, "skills", $PluginName)
    $roots += Join-PathMany @($WorkDir, "skills", $PluginName)
    $roots += Join-PathMany @($WorkDir, "plugins", $PluginName, "skills", $PluginName)
    if ($ScriptDir) {
        $roots += Join-PathMany @($ScriptDir, "..", "skills", $PluginName)
        $roots += Join-PathMany @($ScriptDir, "..", "plugins", $PluginName, "skills", $PluginName)
    }

    foreach ($candidate in $roots) {
        if (Test-SkillSource $candidate) {
            return Resolve-AbsolutePath $candidate
        }
    }
    return ""
}

function Prepare-RuntimeCommands {
    if (-not [string]::IsNullOrWhiteSpace($script:ResolvedUvBin)) {
        $script:McpCommand = $script:ResolvedUvBin
        $script:McpArgs = @(
            "--directory", $script:RepoDir,
            "run",
            "--python", $script:PythonVersion,
            "memory",
            "--db", $script:DbPath,
            "mcp"
        )
        $script:McpEnv = @{}
        $script:InitCommand = $script:ResolvedUvBin
        $script:InitArgs = @(
            "--directory", $script:RepoDir,
            "run",
            "--python", $script:PythonVersion,
            "memory",
            "--db", $script:DbPath,
            "init"
        )
        $script:InitEnv = @{}
        $script:RuntimeLabel = "uv"
        return
    }

    if ([string]::IsNullOrWhiteSpace($script:PythonBin)) {
        Stop-Install "Could not find uv or Python for MCP runtime."
    }

    $script:McpCommand = $script:PythonBin
    $script:McpArgs = @("-m", "pam_os.mcp", "--db", $script:DbPath)
    $script:McpEnv = @{ PYTHONPATH = Join-Path $script:RepoDir "src" }
    $script:InitCommand = $script:PythonBin
    $script:InitArgs = @("-m", "pam_os.cli", "--db", $script:DbPath, "init")
    $script:InitEnv = @{ PYTHONPATH = Join-Path $script:RepoDir "src" }
    $script:RuntimeLabel = "system Python"
}

function Write-McpJson {
    param([string]$Path)
    $payload = @{
        mcpServers = @{
            "pam-os-memory" = @{
                command = $script:McpCommand
                args = $script:McpArgs
                env = $script:McpEnv
            }
        }
    }
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Write-SkillConfig {
    param([string]$Path)

    $escapedPython = ConvertTo-TomlString $script:PythonVersion
    $escapedRepoDir = ConvertTo-TomlString $script:RepoDir
    $escapedDbPath = ConvertTo-TomlString $script:DbPath

    $content = @"
# PAM-OS skill runtime mode.
# Default is CLI. The Codex plugin also registers MCP tools separately.

mode = "cli"

[cli]
python = "$escapedPython"
command = "memory"
repo_dir = "$escapedRepoDir"
db_path = "$escapedDbPath"

[rest]
url = "http://127.0.0.1:8765"
username = ""
password = ""
"@
    Set-Content -LiteralPath $Path -Value $content -Encoding UTF8
}

function Install-GlobalSkill {
    param(
        [string]$Source,
        [string]$Destination,
        [string]$Label
    )

    if (-not (Test-SkillSource $Source)) {
        Write-Warn "Skill source is invalid at $Source; skipped $Label."
        return
    }
    if (-not (Prepare-Destination $Destination $Label)) {
        Write-Warn "Skipped $Label."
        return
    }

    Write-Info "Installing $Label"
    Copy-Directory $Source $Destination
    Write-SkillConfig (Join-Path $Destination "config.toml")
}

function Install-CodexGlobalSkill {
    param(
        [string]$PluginDir,
        [string]$Destination
    )

    $skillSource = Join-PathMany @($PluginDir, "skills", $PluginName)
    if (-not (Test-SkillSource $skillSource)) {
        Write-Warn "Plugin does not contain a bundled skill at $skillSource; skipped Codex global skill install."
        return
    }
    Install-GlobalSkill $skillSource $Destination "Codex global skill fallback"
}

function Write-MarketplaceConfig {
    param([string]$Path)

    $payloadIsDictionary = $false
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        if ($null -eq $payload) {
            Stop-Install "$Path must contain a JSON object."
        }
    }
    else {
        $payload = [ordered]@{
            name = "personal"
            interface = [ordered]@{
                displayName = "Personal"
            }
            plugins = @()
        }
        $payloadIsDictionary = $true
    }

    if ($payload -is [System.Collections.IDictionary]) {
        $payloadIsDictionary = $true
    }

    if ($payloadIsDictionary) {
        if (-not $payload.Contains("plugins") -or $null -eq $payload["plugins"]) {
            $payload["plugins"] = @()
        }
        $currentPlugins = $payload["plugins"]
    }
    else {
        if (-not ($payload.PSObject.Properties.Name -contains "plugins") -or $null -eq $payload.plugins) {
            $payload | Add-Member -MemberType NoteProperty -Name "plugins" -Value @()
        }
        $currentPlugins = $payload.plugins
    }

    if (-not ($currentPlugins -is [System.Collections.IEnumerable])) {
        Stop-Install "$Path field 'plugins' must be an array."
    }

    $entry = [ordered]@{
        name = $PluginName
        source = [ordered]@{
            source = "local"
            path = "./plugins/$PluginName"
        }
        policy = [ordered]@{
            installation = "INSTALLED_BY_DEFAULT"
            authentication = "ON_INSTALL"
        }
        category = "Productivity"
        version = "0.2.1"
    }

    $plugins = @($currentPlugins)
    $updated = $false
    for ($i = 0; $i -lt $plugins.Count; $i++) {
        if ($plugins[$i].name -eq $PluginName) {
            $plugins[$i] = $entry
            $updated = $true
            break
        }
    }
    if (-not $updated) {
        $plugins += $entry
    }
    if ($payloadIsDictionary) {
        $payload["plugins"] = $plugins
    }
    else {
        $payload.plugins = $plugins
    }

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Write-CodexMcpConfig {
    param([string]$Path)

    $serverHeader = "[mcp_servers.$McpServerName]"
    $serverChildPrefix = "[mcp_servers.$McpServerName."

    $block = New-Object System.Collections.Generic.List[string]
    $block.Add($serverHeader)
    $block.Add("command = $(ConvertTo-JsonString $script:McpCommand)")
    $block.Add("args = [")
    foreach ($arg in $script:McpArgs) {
        $block.Add("  $(ConvertTo-JsonString $arg),")
    }
    $block.Add("]")
    $block.Add('description = "PAM-OS local-first long-term memory"')
    $block.Add("")
    if ($script:McpEnv.Count -gt 0) {
        $block.Add("[mcp_servers.$McpServerName.env]")
        foreach ($key in ($script:McpEnv.Keys | Sort-Object)) {
            $block.Add("$key = $(ConvertTo-JsonString ([string]$script:McpEnv[$key]))")
        }
        $block.Add("")
    }

    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $lines = Get-Content -LiteralPath $Path
    }
    else {
        $lines = @()
    }

    $output = New-Object System.Collections.Generic.List[string]
    $index = 0
    $replaced = $false
    while ($index -lt $lines.Count) {
        $line = $lines[$index]
        $stripped = $line.Trim()
        if ($stripped -eq $serverHeader -or $stripped.StartsWith($serverChildPrefix)) {
            if (-not $replaced) {
                foreach ($blockLine in $block) { $output.Add($blockLine) }
                $replaced = $true
            }
            $index++
            while ($index -lt $lines.Count) {
                $next = $lines[$index].Trim()
                if ($next.StartsWith("[") -and $next.EndsWith("]") -and -not ($next -eq $serverHeader -or $next.StartsWith($serverChildPrefix))) {
                    break
                }
                $index++
            }
            continue
        }
        $output.Add($line)
        $index++
    }

    if (-not $replaced) {
        if ($output.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($output[$output.Count - 1])) {
            $output.Add("")
        }
        if (-not ($output | Where-Object { $_.Trim() -eq "[mcp_servers]" })) {
            $output.Add("[mcp_servers]")
            $output.Add("")
        }
        foreach ($blockLine in $block) { $output.Add($blockLine) }
    }

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Set-Content -LiteralPath $Path -Value $output -Encoding UTF8
}

function Update-ManagedGuidance {
    param(
        [string]$File,
        [string]$SkillPath
    )

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
    $output.Add("Prefer MCP tools from the pam_os_memory server when available. If MCP is unavailable, read the installed skill instructions from ``$SkillPath``.")
    $output.Add("")
    $output.Add("Do not store secrets or sensitive details unless the user explicitly asks to remember them.")
    $output.Add($end)

    Set-Content -LiteralPath $File -Value $output -Encoding UTF8
}

function Write-HermesMcpConfig {
    param([string]$Path)

    $block = New-Object System.Collections.Generic.List[string]
    $block.Add("  ${McpServerName}:")
    $block.Add("    command: $(ConvertTo-JsonString $script:McpCommand)")
    $block.Add("    args:")
    foreach ($arg in $script:McpArgs) {
        $block.Add("      - $(ConvertTo-JsonString $arg)")
    }
    if ($script:McpEnv.Count -gt 0) {
        $block.Add("    env:")
        foreach ($key in ($script:McpEnv.Keys | Sort-Object)) {
            $block.Add("      ${key}: $(ConvertTo-JsonString ([string]$script:McpEnv[$key]))")
        }
    }

    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $lines = Get-Content -LiteralPath $Path
    }
    else {
        $lines = @()
    }

    $output = New-Object System.Collections.Generic.List[string]
    $index = 0
    $inMcp = $false
    $foundMcp = $false
    $replaced = $false
    while ($index -lt $lines.Count) {
        $line = $lines[$index]
        $stripped = $line.Trim()
        if ($line -eq "mcp_servers:") {
            $foundMcp = $true
            $inMcp = $true
            $output.Add($line)
            $index++
            continue
        }
        if ($inMcp -and $line.StartsWith("  ") -and $stripped -eq "${McpServerName}:") {
            foreach ($blockLine in $block) { $output.Add($blockLine) }
            $replaced = $true
            $index++
            while ($index -lt $lines.Count) {
                $next = $lines[$index]
                if ($next -and -not $next.StartsWith("    ") -and -not $next.StartsWith("      ")) {
                    break
                }
                $index++
            }
            continue
        }
        if ($inMcp -and $line -and -not $line.StartsWith(" ")) {
            if (-not $replaced) {
                foreach ($blockLine in $block) { $output.Add($blockLine) }
                $replaced = $true
            }
            $inMcp = $false
        }
        $output.Add($line)
        $index++
    }

    if (-not $foundMcp) {
        if ($output.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($output[$output.Count - 1])) {
            $output.Add("")
        }
        $output.Add("mcp_servers:")
        foreach ($blockLine in $block) { $output.Add($blockLine) }
    }
    elseif (-not $replaced) {
        foreach ($blockLine in $block) { $output.Add($blockLine) }
    }

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Set-Content -LiteralPath $Path -Value $output -Encoding UTF8
}

function Invoke-CliInit {
    if (-not $script:RunInit) {
        return
    }
    if (-not (Confirm-Action "Initialize PAM-OS memory database and warm up the selected runtime?" "y")) {
        Write-Warn "Skipped PAM-OS memory database init."
        return
    }

    Write-Info "Initializing PAM-OS memory database and warming selected runtime"
    $oldEnv = @{}
    foreach ($key in $script:InitEnv.Keys) {
        $oldEnv[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$script:InitEnv[$key], "Process")
    }
    try {
        & $script:InitCommand @script:InitArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "PAM-OS memory database init or runtime warmup failed."
            Write-Warn "Run manually later: $($script:InitCommand) $($script:InitArgs -join ' ')"
        }
    }
    finally {
        foreach ($key in $script:InitEnv.Keys) {
            [Environment]::SetEnvironmentVariable($key, $oldEnv[$key], "Process")
        }
    }
}

function Show-Summary {
    $mcpEnvJson = $script:McpEnv | ConvertTo-Json -Compress
    @"

Done.

Next checks:
  Codex:   restart Codex, list skills, and verify the pam_os_memory MCP server.
  Claude:  restart Claude Code, then list skills or invoke /pam-os-memory.
  OpenCode: restart opencode so it reloads AGENTS.md guidance.
  Hermes:  restart Hermes and verify the pam_os_memory MCP server is listed.

Marketplace:
  $($script:MarketplacePath)

Skill paths:
  $($script:CodexSkillDir)
  $($script:ClaudeSkillDir)

Guidance/config:
  $($script:OpenCodeAgentsFile)
  $($script:HermesConfig)
  $($script:HermesAgentsFile)

Managed/runtime repo:
  $($script:RepoDir)

MCP command:
  $($script:McpCommand) $($script:McpArgs -join ' ')

Runtime:
  $($script:RuntimeLabel)

MCP environment:
  $mcpEnvJson

"@ | Write-Host
}

try {
    $script:AssumeYes = $false
    $script:InstallCodex = $false
    $script:InstallClaude = $false
    $script:InstallOpenCode = $false
    $script:InstallHermes = $false
    $script:PluginDir = $DefaultPluginDir
    $script:MarketplacePath = $DefaultMarketplacePath
    $script:CodexConfig = $DefaultCodexConfig
    $script:CodexSkillDir = $DefaultCodexSkillDir
    $script:ClaudeSkillDir = $DefaultClaudeSkillDir
    $script:OpenCodeAgentsFile = $DefaultOpenCodeAgentsFile
    $script:HermesConfig = $DefaultHermesConfig
    $script:HermesAgentsFile = $DefaultHermesAgentsFile
    $script:RepoUrl = $DefaultRepoUrl
    $script:RepoRef = $DefaultRepoRef
    $script:RepoDir = $DefaultRepoDir
    $script:RepoDirExplicit = $false
    $script:RefreshRepo = $true
    $script:DbPath = $DefaultDbPath
    $script:PythonVersion = Get-EnvOrDefault "PAM_OS_CLI_PYTHON" "3.12"
    $script:UvBin = Get-EnvOrDefault "PAM_OS_UV_BIN" ""
    $script:SourceDir = ""
    $script:WriteMarketplace = $true
    $script:WriteMcpConfig = $true
    $script:WriteGlobalSkill = $true
    $script:RunInit = $true
    $script:ResolvedUvBin = ""
    $script:PythonBin = ""
    $script:McpCommand = ""
    $script:McpArgs = @()
    $script:McpEnv = @{}
    $script:InitCommand = ""
    $script:InitArgs = @()
    $script:InitEnv = @{}
    $script:RuntimeLabel = ""

    for ($i = 0; $i -lt $CliArgs.Count; $i++) {
        $arg = $CliArgs[$i]
        switch ($arg) {
            "--target" {
                $i++
                $target = Get-OptionValue $arg $i
                Enable-Target $target
            }
            "--codex" { $script:InstallCodex = $true }
            "--claude" { $script:InstallClaude = $true }
            "--opencode" { $script:InstallOpenCode = $true }
            "--hermes" { $script:InstallHermes = $true }
            "--all" { Enable-Target "all" }
            "--plugin-dir" {
                $i++
                $script:PluginDir = Get-OptionValue $arg $i
            }
            "--marketplace" {
                $i++
                $script:MarketplacePath = Get-OptionValue $arg $i
            }
            "--codex-config" {
                $i++
                $script:CodexConfig = Get-OptionValue $arg $i
            }
            "--codex-skill-dir" {
                $i++
                $script:CodexSkillDir = Get-OptionValue $arg $i
            }
            "--claude-skill-dir" {
                $i++
                $script:ClaudeSkillDir = Get-OptionValue $arg $i
            }
            "--opencode-agents" {
                $i++
                $script:OpenCodeAgentsFile = Get-OptionValue $arg $i
            }
            "--hermes-config" {
                $i++
                $script:HermesConfig = Get-OptionValue $arg $i
            }
            "--hermes-agents" {
                $i++
                $script:HermesAgentsFile = Get-OptionValue $arg $i
            }
            "--repo-dir" {
                $i++
                $script:RepoDir = Get-OptionValue $arg $i
                $script:RepoDirExplicit = $true
                $script:RefreshRepo = $false
            }
            "--repo-url" {
                $i++
                $script:RepoUrl = Get-OptionValue $arg $i
            }
            "--ref" {
                $i++
                $script:RepoRef = Get-OptionValue $arg $i
            }
            "--no-refresh" { $script:RefreshRepo = $false }
            "--db" {
                $i++
                $script:DbPath = Get-OptionValue $arg $i
            }
            "--python" {
                $i++
                $script:PythonVersion = Get-OptionValue $arg $i
            }
            "--uv-bin" {
                $i++
                $script:UvBin = Get-OptionValue $arg $i
            }
            "--source" {
                $i++
                $script:SourceDir = Get-OptionValue $arg $i
            }
            "--skip-marketplace" { $script:WriteMarketplace = $false }
            "--skip-mcp-config" { $script:WriteMcpConfig = $false }
            "--skip-global-skill" { $script:WriteGlobalSkill = $false }
            "--no-init" { $script:RunInit = $false }
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

    foreach ($pair in @(
        @("--plugin-dir", $script:PluginDir),
        @("--marketplace", $script:MarketplacePath),
        @("--codex-config", $script:CodexConfig),
        @("--codex-skill-dir", $script:CodexSkillDir),
        @("--claude-skill-dir", $script:ClaudeSkillDir),
        @("--opencode-agents", $script:OpenCodeAgentsFile),
        @("--hermes-config", $script:HermesConfig),
        @("--hermes-agents", $script:HermesAgentsFile),
        @("--repo-url", $script:RepoUrl),
        @("--ref", $script:RepoRef),
        @("--repo-dir", $script:RepoDir),
        @("--db", $script:DbPath),
        @("--python", $script:PythonVersion)
    )) {
        if ([string]::IsNullOrWhiteSpace($pair[1])) {
            Stop-Install "$($pair[0]) must not be empty."
        }
    }

    if (-not $script:AssumeYes -and -not (Test-CanPrompt)) {
        Stop-Install "Interactive install requires a user session. Use --yes with explicit options for non-interactive installs."
    }

    Write-Info "PAM-OS plugin installer"

    if (-not ($script:InstallCodex -or $script:InstallClaude -or $script:InstallOpenCode -or $script:InstallHermes)) {
        if ($script:AssumeYes) {
            $script:InstallCodex = $true
        }
        else {
            Select-InstallTargets
        }
    }
    if (-not ($script:InstallCodex -or $script:InstallClaude -or $script:InstallOpenCode -or $script:InstallHermes)) {
        Stop-Install "No install targets selected."
    }

    $script:DbPath = Resolve-AbsolutePath $script:DbPath
    $script:PluginDir = Resolve-AbsolutePath $script:PluginDir
    $script:MarketplacePath = Resolve-AbsolutePath $script:MarketplacePath
    $script:CodexConfig = Resolve-AbsolutePath $script:CodexConfig
    $script:CodexSkillDir = Resolve-AbsolutePath $script:CodexSkillDir
    $script:ClaudeSkillDir = Resolve-AbsolutePath $script:ClaudeSkillDir
    $script:OpenCodeAgentsFile = Resolve-AbsolutePath $script:OpenCodeAgentsFile
    $script:HermesConfig = Resolve-AbsolutePath $script:HermesConfig
    $script:HermesAgentsFile = Resolve-AbsolutePath $script:HermesAgentsFile
    if (-not [string]::IsNullOrWhiteSpace($script:SourceDir)) {
        $script:SourceDir = Resolve-AbsolutePath $script:SourceDir
    }

    $script:ResolvedUvBin = Find-UvBin
    $script:PythonBin = Find-PythonBin
    Resolve-RepoDir

    $pluginSource = ""
    if ($script:InstallCodex) {
        $pluginSource = Find-PluginSource
        if ([string]::IsNullOrWhiteSpace($pluginSource)) {
            Stop-Install "Could not find plugin source. Run from a PAM-OS checkout or pass --source."
        }
    }

    $skillSource = Find-SkillSource
    if (($script:InstallClaude -or $script:InstallOpenCode -or $script:InstallHermes -or $script:WriteGlobalSkill) -and [string]::IsNullOrWhiteSpace($skillSource)) {
        Stop-Install "Could not find skill source. Run from a PAM-OS checkout or pass --source."
    }

    Prepare-RuntimeCommands

    if ($script:InstallCodex) {
        if (Prepare-Destination $script:PluginDir "Codex plugin") {
            Write-Info "Installing Codex plugin from $pluginSource"
            Copy-Directory $pluginSource $script:PluginDir
            Write-McpJson (Join-Path $script:PluginDir ".mcp.json")

            if ($script:WriteGlobalSkill) {
                Install-CodexGlobalSkill $script:PluginDir $script:CodexSkillDir
            }
            if ($script:WriteMarketplace) {
                Write-MarketplaceConfig $script:MarketplacePath
                Write-Info "Updated marketplace: $($script:MarketplacePath)"
            }
            if ($script:WriteMcpConfig) {
                Write-CodexMcpConfig $script:CodexConfig
                Write-Info "Registered MCP server '$McpServerName' in $($script:CodexConfig)"
            }
        }
        else {
            Write-Warn "Skipped Codex plugin install."
        }
    }

    if ($script:InstallClaude) {
        Install-GlobalSkill $skillSource $script:ClaudeSkillDir "Claude Code global skill"
    }

    if ($script:InstallOpenCode) {
        Write-Info "Installing OpenCode compatibility"
        if (-not $script:InstallClaude) {
            Install-GlobalSkill $skillSource $script:ClaudeSkillDir "OpenCode Claude-compatible skill"
        }
        else {
            Write-Info "Claude-compatible skill target is already handled by the Claude Code install."
        }
        Update-ManagedGuidance $script:OpenCodeAgentsFile (Join-Path $script:ClaudeSkillDir "SKILL.md")
        Write-Host "Updated: $($script:OpenCodeAgentsFile)"
    }

    if ($script:InstallHermes) {
        Write-Info "Installing Hermes compatibility"
        Write-HermesMcpConfig $script:HermesConfig
        Update-ManagedGuidance $script:HermesAgentsFile (Join-Path $skillSource "SKILL.md")
        Write-Host "Updated: $($script:HermesConfig)"
        Write-Host "Updated: $($script:HermesAgentsFile)"
    }

    Invoke-CliInit
    Show-Summary
}
finally {
}
