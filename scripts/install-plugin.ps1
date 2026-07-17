#requires -Version 5.1

$ErrorActionPreference = "Stop"
$InstallerArgs = $args

function Get-EnvOrDefault {
    param([string]$Name, [string]$Default)
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

function Join-PathMany {
    param([string[]]$Parts)
    $path = $Parts[0]
    for ($i = 1; $i -lt $Parts.Count; $i++) { $path = Join-Path $path $Parts[$i] }
    return $path
}

$PluginName = Get-EnvOrDefault "PAM_OS_PLUGIN_NAME" "pam-os-memory"
$HomeDir = $HOME
$LocalAppDataDir = Get-EnvOrDefault "LOCALAPPDATA" (Join-PathMany @($HomeDir, "AppData", "Local"))
$AppDataDir = Get-EnvOrDefault "APPDATA" (Join-PathMany @($HomeDir, "AppData", "Roaming"))
$CodexHome = Get-EnvOrDefault "CODEX_HOME" (Join-Path $HomeDir ".codex")
$HermesHome = Get-EnvOrDefault "HERMES_HOME" (Join-Path $HomeDir ".hermes")
$DefaultRepoUrl = Get-EnvOrDefault "PAM_OS_REPO_URL" "https://github.com/danzhewuju/PAM-OS.git"
$DefaultRepoRef = Get-EnvOrDefault "PAM_OS_REPO_REF" "master"
$DefaultRepoDir = Get-EnvOrDefault "PAM_OS_REPO_DIR" (Join-PathMany @($LocalAppDataDir, "pam-os", "repo"))
$DefaultPluginDir = Join-PathMany @($HomeDir, "plugins", $PluginName)
$DefaultMarketplacePath = Join-PathMany @($HomeDir, ".agents", "plugins", "marketplace.json")
$DefaultCodexConfig = Join-Path $CodexHome "config.toml"
$DefaultCodexSkillDir = Join-PathMany @($CodexHome, "skills", $PluginName)
$DefaultClaudeSkillDir = Join-PathMany @($HomeDir, ".claude", "skills", $PluginName)
$DefaultOpenCodeAgentsFile = Join-PathMany @($AppDataDir, "opencode", "AGENTS.md")
$DefaultHermesAgentsFile = Join-Path $HermesHome "AGENTS.md"
$DefaultHermesSkillDir = Join-PathMany @($HermesHome, "skills", $PluginName)
$LegacyServerName = "pam_os_memory"

function Write-Info { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Blue }
function Write-Warn { param([string]$Message) Write-Warning $Message }
function Stop-Install { param([string]$Message) Write-Error "error: $Message"; exit 1 }

function Show-Usage {
    @"
PAM-OS plugin installer for Windows

Usage:
  .\scripts\install-plugin.ps1 [options]

Options:
  --target TARGET      Install target: codex, claude, opencode, hermes, or all. Can be repeated.
  --codex             Install the Codex plugin and global skill.
  --claude            Install the Claude Code global skill.
  --opencode          Install OpenCode guidance and Claude-compatible skill.
  --hermes            Install Hermes skill and guidance.
  --all               Install all supported targets.
  --rest-url URL      PAM-OS REST server URL. Default: http://127.0.0.1:8765.
  --rest-username USER
                      REST Basic Auth username. Default: empty.
  --rest-password PASS
                      REST Basic Auth password. Default: empty.
  --rest-timeout SEC  REST request timeout written to skill config. Default: 10.
  --repo-dir DIR      Use an existing PAM-OS checkout. Default: $DefaultRepoDir.
  --repo-url URL      Git repository used to refresh the managed repo.
  --ref REF           Git ref used to refresh the managed repo. Default: master.
  --source DIR        Existing pam-os-memory plugin source directory for dev/local installs.
  --plugin-dir DIR    Destination Codex plugin dir. Default: $DefaultPluginDir.
  --marketplace PATH  Personal marketplace path. Default: $DefaultMarketplacePath.
  --codex-config PATH Codex config.toml path used only for legacy cleanup.
  --codex-skill-dir DIR
                      Codex global skill dir. Default: $DefaultCodexSkillDir.
  --claude-skill-dir DIR
                      Claude Code skill dir. Default: $DefaultClaudeSkillDir.
  --opencode-agents PATH
                      OpenCode AGENTS.md path. Default: $DefaultOpenCodeAgentsFile.
  --hermes-agents PATH
                      Hermes AGENTS.md path. Default: $DefaultHermesAgentsFile.
  --hermes-skill-dir DIR
                      Hermes skill dir. Default: $DefaultHermesSkillDir.
  --skip-marketplace  Do not create or update the personal plugin marketplace entry.
  --skip-global-skill Do not install the Codex global skill.
  --no-refresh        Do not fetch or clone the managed repo before installing.
  --yes               Replace existing installs without prompting.
  -h, --help          Show this help.

PAM-OS uses a REST-only adapter. This installer writes the REST skill config
and removes legacy local tool registrations it manages.
"@ | Write-Host
}

function Test-CanPrompt {
    try { return [Environment]::UserInteractive -and -not [Console]::IsInputRedirected }
    catch { return [Environment]::UserInteractive }
}

function Read-User {
    param([string]$Prompt)
    if (-not (Test-CanPrompt)) { Stop-Install "Interactive prompt requires a user session. Re-run with --yes or explicit options." }
    return Read-Host $Prompt
}

function Confirm-Action {
    param([string]$Prompt, [string]$Default = "y")
    if ($script:AssumeYes) { return $Default -eq "y" }
    $suffix = if ($Default -eq "y") { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $reply = Read-User "$Prompt $suffix"
        if ([string]::IsNullOrWhiteSpace($reply)) { $reply = $Default }
        switch -Regex ($reply) {
            "^(y|yes)$" { return $true }
            "^(n|no)$" { return $false }
            default { Write-Host "Please answer y or n." }
        }
    }
}

function Prompt-Value {
    param([string]$Prompt, [string]$Default)
    if ($script:AssumeYes) { return $Default }
    $promptText = if ([string]::IsNullOrWhiteSpace($Default)) { "$Prompt (leave empty for none)" } else { "$Prompt [$Default]" }
    $reply = Read-User $promptText
    if ([string]::IsNullOrWhiteSpace($reply)) { return $Default }
    return $reply
}

function Prompt-Secret {
    param([string]$Prompt, [string]$Default)
    if ($script:AssumeYes) { return $Default }
    $secure = Read-Host "$Prompt (leave empty for none)" -AsSecureString
    if ($secure.Length -eq 0) { return $Default }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Resolve-AbsolutePath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
    return [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($Path))
}

function ConvertTo-TomlString {
    param([string]$Value)
    if ($null -eq $Value) { $Value = "" }
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

function Select-InstallTargets {
    Write-Host ""
    Write-Host "Install targets:"
    Write-Host "  1) codex    - Codex plugin + global skill"
    Write-Host "  2) claude   - Claude Code global skill"
    Write-Host "  3) opencode - OpenCode guidance"
    Write-Host "  4) hermes   - Hermes skill + guidance"
    Write-Host "  5) all"
    while ($true) {
        $selection = Read-User "Selection [1]"
        if ([string]::IsNullOrWhiteSpace($selection)) { $selection = "1" }
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
                default { Write-Warn "Unknown target: $item"; $valid = $false; break }
            }
        }
        if ($valid -and ($script:InstallCodex -or $script:InstallClaude -or $script:InstallOpenCode -or $script:InstallHermes)) { return }
    }
}

function Refresh-ManagedRepo {
    if (-not $script:RefreshRepo) { return }
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($null -eq $git) { Stop-Install "git is required to refresh the managed PAM-OS repo. Re-run with --no-refresh or --repo-dir." }
    if (Test-Path -LiteralPath (Join-Path $script:RepoDir ".git") -PathType Container) {
        Write-Info "Refreshing managed PAM-OS repo at $($script:RepoDir) ($($script:RepoRef))"
        & git -C $script:RepoDir fetch --depth 1 origin $script:RepoRef | Out-Null
        & git -C $script:RepoDir checkout -q FETCH_HEAD
        return
    }
    if (Test-Path -LiteralPath $script:RepoDir) { Stop-Install "Managed repo path exists but is not a git checkout: $($script:RepoDir)" }
    Write-Info "Cloning managed PAM-OS repo into $($script:RepoDir) ($($script:RepoRef))"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $script:RepoDir) | Out-Null
    & git clone --depth 1 --branch $script:RepoRef $script:RepoUrl $script:RepoDir | Out-Null
}

function Resolve-RepoDir {
    if ($script:RepoDirExplicit) {
        $script:RepoDir = Resolve-AbsolutePath $script:RepoDir
        if (-not (Test-PamRepo $script:RepoDir)) { Stop-Install "--repo-dir is not a PAM-OS checkout: $($script:RepoDir)" }
        return
    }
    if (-not [string]::IsNullOrWhiteSpace($script:SourceDir)) {
        $inferred = Resolve-AbsolutePath (Join-Path $script:SourceDir "..\..")
        if (Test-PamRepo $inferred) {
            $script:RepoDir = $inferred
            $script:RefreshRepo = $false
            return
        }
    }
    Refresh-ManagedRepo
    $script:RepoDir = Resolve-AbsolutePath $script:RepoDir
    if (-not (Test-PamRepo $script:RepoDir)) { Stop-Install "Could not find a PAM-OS repo: $($script:RepoDir)" }
}

function Find-PluginSource {
    foreach ($candidate in @($script:SourceDir, (Join-PathMany @($script:RepoDir, "plugins", $PluginName)))) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath (Join-PathMany @($candidate, ".codex-plugin", "plugin.json")) -PathType Leaf)) {
            return Resolve-AbsolutePath $candidate
        }
    }
    return ""
}

function Find-SkillSource {
    foreach ($candidate in @(
        (Join-PathMany @($script:RepoDir, "skills", $PluginName)),
        (Join-PathMany @($script:RepoDir, "plugins", $PluginName, "skills", $PluginName)),
        (Join-PathMany @($script:SourceDir, "skills", $PluginName))
    )) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath (Join-Path $candidate "SKILL.md") -PathType Leaf)) {
            return Resolve-AbsolutePath $candidate
        }
    }
    return ""
}

function Copy-Directory {
    param([string]$Source, [string]$Destination)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

function Write-SkillConfig {
    param([string]$Path)
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $content = @"
# PAM-OS REST client configuration.

[rest]
url = "$(ConvertTo-TomlString $script:RestUrl)"
username = "$(ConvertTo-TomlString $script:RestUsername)"
password = "$(ConvertTo-TomlString $script:RestPassword)"
timeout_seconds = $($script:RestTimeoutSeconds)
"@
    Set-Content -LiteralPath $Path -Value $content -Encoding UTF8
    if ($env:OS -eq "Windows_NT") {
        $acl = Get-Acl -LiteralPath $Path
        $acl.SetAccessRuleProtection($true, $false)
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, "FullControl", "Allow")
        $acl.SetAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl
    }
}

function Install-Skill {
    param([string]$Source, [string]$Destination, [string]$Label)
    if (Test-Path -LiteralPath $Destination) {
        if (Confirm-Action "Replace existing $Label at $Destination?" "y") {
            Remove-Item -LiteralPath $Destination -Recurse -Force
        }
        else {
            Write-Warn "Skipped $Label install."
            return
        }
    }
    Write-Info "Installing $Label to $Destination"
    Copy-Directory $Source $Destination
    Write-SkillConfig (Join-Path $Destination "config.toml")
}

function Write-BundledSkillConfig {
    param([string]$PluginDir)
    $skillDir = Join-PathMany @($PluginDir, "skills", $PluginName)
    if (Test-Path -LiteralPath $skillDir -PathType Container) {
        Write-SkillConfig (Join-Path $skillDir "config.toml")
    }
    Remove-Item -LiteralPath (Join-Path $PluginDir ".mcp.json") -Force -ErrorAction SilentlyContinue
}

function Write-MarketplaceConfig {
    param([string]$Path)
    $payload = if (Test-Path -LiteralPath $Path -PathType Leaf) {
        Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    else {
        [pscustomobject]@{ name = "personal"; interface = [pscustomobject]@{ displayName = "Personal" }; plugins = @() }
    }
    if ($null -eq $payload.plugins) { $payload | Add-Member -NotePropertyName plugins -NotePropertyValue @() }
    $entry = [pscustomobject]@{
        name = $PluginName
        source = [pscustomobject]@{ source = "local"; path = "./plugins/$PluginName" }
        policy = [pscustomobject]@{ installation = "INSTALLED_BY_DEFAULT"; authentication = "ON_INSTALL" }
        category = "Productivity"
    }
    $plugins = @($payload.plugins | Where-Object { $_.name -ne $PluginName })
    $payload.plugins = @($plugins + $entry)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $payload | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Remove-LegacyCodexConfig {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $lines = Get-Content -LiteralPath $Path
    $serverHeader = "[mcp_servers.$LegacyServerName]"
    $serverChildPrefix = "[mcp_servers.$LegacyServerName."
    $output = New-Object System.Collections.Generic.List[string]
    $index = 0
    $removed = $false
    while ($index -lt $lines.Count) {
        $line = $lines[$index]
        $stripped = $line.Trim()
        if ($stripped -eq $serverHeader -or $stripped.StartsWith($serverChildPrefix)) {
            $removed = $true
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
    if ($removed) {
        Set-Content -LiteralPath $Path -Value $output -Encoding UTF8
    }
}

function Update-Guidance {
    param([string]$Path, [string]$SkillPath)
    $begin = "<!-- PAM-OS MEMORY BEGIN -->"
    $end = "<!-- PAM-OS MEMORY END -->"
    $existing = if (Test-Path -LiteralPath $Path -PathType Leaf) { Get-Content -LiteralPath $Path -Raw -Encoding UTF8 } else { "" }
    while ($existing.Contains($begin) -and $existing.Contains($end)) {
        $start = $existing.IndexOf($begin)
        $finish = $existing.IndexOf($end, $start) + $end.Length
        $existing = ($existing.Remove($start, $finish - $start)).Trim() + "`n"
    }
    $block = @"
$begin
Use the installed PAM-OS skill from `$SkillPath`. Read its `config.toml` first and call the configured PAM-OS REST API.
$end
"@
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $content = if ([string]::IsNullOrWhiteSpace($existing)) { $block } else { $existing.TrimEnd() + "`n`n" + $block }
    Set-Content -LiteralPath $Path -Value $content -Encoding UTF8
}

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
$script:HermesAgentsFile = $DefaultHermesAgentsFile
$script:HermesSkillDir = $DefaultHermesSkillDir
$script:RepoUrl = $DefaultRepoUrl
$script:RepoRef = $DefaultRepoRef
$script:RepoDir = $DefaultRepoDir
$script:RepoDirExplicit = $false
$script:RefreshRepo = $true
$script:SourceDir = ""
$script:RestUrl = Get-EnvOrDefault "PAM_OS_REST_URL" "http://127.0.0.1:8765"
$script:RestUsername = Get-EnvOrDefault "PAM_OS_REST_USERNAME" ""
$script:RestPassword = Get-EnvOrDefault "PAM_OS_REST_PASSWORD" ""
$script:RestTimeoutSeconds = [int](Get-EnvOrDefault "PAM_OS_REST_TIMEOUT_SECONDS" "10")
$script:WriteMarketplace = $true
$script:WriteGlobalSkill = $true

for ($i = 0; $i -lt $InstallerArgs.Count; $i++) {
    $arg = $InstallerArgs[$i]
    switch ($arg) {
        "--target" { $i++; Enable-Target $InstallerArgs[$i] }
        "--codex" { $script:InstallCodex = $true }
        "--claude" { $script:InstallClaude = $true }
        "--opencode" { $script:InstallOpenCode = $true }
        "--hermes" { $script:InstallHermes = $true }
        "--all" { Enable-Target "all" }
        "--rest-url" { $i++; $script:RestUrl = $InstallerArgs[$i] }
        "--rest-username" { $i++; $script:RestUsername = $InstallerArgs[$i] }
        "--rest-user" { $i++; $script:RestUsername = $InstallerArgs[$i] }
        "--rest-password" { $i++; $script:RestPassword = $InstallerArgs[$i] }
        "--rest-timeout" { $i++; $script:RestTimeoutSeconds = [int]$InstallerArgs[$i] }
        "--repo-dir" { $i++; $script:RepoDir = $InstallerArgs[$i]; $script:RepoDirExplicit = $true; $script:RefreshRepo = $false }
        "--repo-url" { $i++; $script:RepoUrl = $InstallerArgs[$i] }
        "--ref" { $i++; $script:RepoRef = $InstallerArgs[$i] }
        "--source" { $i++; $script:SourceDir = $InstallerArgs[$i] }
        "--plugin-dir" { $i++; $script:PluginDir = $InstallerArgs[$i] }
        "--marketplace" { $i++; $script:MarketplacePath = $InstallerArgs[$i] }
        "--codex-config" { $i++; $script:CodexConfig = $InstallerArgs[$i] }
        "--codex-skill-dir" { $i++; $script:CodexSkillDir = $InstallerArgs[$i] }
        "--claude-skill-dir" { $i++; $script:ClaudeSkillDir = $InstallerArgs[$i] }
        "--opencode-agents" { $i++; $script:OpenCodeAgentsFile = $InstallerArgs[$i] }
        "--hermes-agents" { $i++; $script:HermesAgentsFile = $InstallerArgs[$i] }
        "--hermes-skill-dir" { $i++; $script:HermesSkillDir = $InstallerArgs[$i] }
        "--skip-marketplace" { $script:WriteMarketplace = $false }
        "--skip-global-skill" { $script:WriteGlobalSkill = $false }
        "--no-refresh" { $script:RefreshRepo = $false }
        "--skip-mcp-config" {}
        "--no-init" {}
        "--claude-mcp-scope" { $i++ }
        "--hermes-config" { $i++ }
        "--yes" { $script:AssumeYes = $true }
        "--non-interactive" { $script:AssumeYes = $true }
        "-h" { Show-Usage; exit 0 }
        "--help" { Show-Usage; exit 0 }
        default { Stop-Install "Unknown option: $arg" }
    }
}

if (-not ($script:InstallCodex -or $script:InstallClaude -or $script:InstallOpenCode -or $script:InstallHermes)) {
    if ($script:AssumeYes) { $script:InstallCodex = $true }
    else { Select-InstallTargets }
}

$script:RestUrl = Prompt-Value "PAM-OS REST URL" $script:RestUrl
$script:RestUsername = Prompt-Value "REST username" $script:RestUsername
$script:RestPassword = Prompt-Secret "REST password" $script:RestPassword
if ([string]::IsNullOrWhiteSpace($script:RestUrl)) { Stop-Install "--rest-url must not be empty." }
if ($script:RestTimeoutSeconds -le 0) { Stop-Install "--rest-timeout must be a positive integer." }

$script:PluginDir = Resolve-AbsolutePath $script:PluginDir
$script:MarketplacePath = Resolve-AbsolutePath $script:MarketplacePath
$script:CodexConfig = Resolve-AbsolutePath $script:CodexConfig
$script:CodexSkillDir = Resolve-AbsolutePath $script:CodexSkillDir
$script:ClaudeSkillDir = Resolve-AbsolutePath $script:ClaudeSkillDir
$script:OpenCodeAgentsFile = Resolve-AbsolutePath $script:OpenCodeAgentsFile
$script:HermesAgentsFile = Resolve-AbsolutePath $script:HermesAgentsFile
$script:HermesSkillDir = Resolve-AbsolutePath $script:HermesSkillDir
if (-not [string]::IsNullOrWhiteSpace($script:SourceDir)) { $script:SourceDir = Resolve-AbsolutePath $script:SourceDir }

Resolve-RepoDir
$pluginSource = Find-PluginSource
$skillSource = Find-SkillSource
if ($script:InstallCodex -and [string]::IsNullOrWhiteSpace($pluginSource)) { Stop-Install "Could not find plugin source. Run from a PAM-OS checkout or pass --source." }
if ([string]::IsNullOrWhiteSpace($skillSource)) { Stop-Install "Could not find skill source. Run from a PAM-OS checkout or pass --source." }

if ($script:InstallCodex) {
    if (Test-Path -LiteralPath $script:PluginDir) {
        if (Confirm-Action "Replace existing Codex plugin at $($script:PluginDir)?" "y") {
            Remove-Item -LiteralPath $script:PluginDir -Recurse -Force
        }
        else {
            Write-Warn "Skipped Codex plugin install."
            $script:InstallCodex = $false
        }
    }
    if ($script:InstallCodex) {
        Write-Info "Installing Codex plugin from $pluginSource"
        Copy-Directory $pluginSource $script:PluginDir
        Write-BundledSkillConfig $script:PluginDir
        Remove-LegacyCodexConfig $script:CodexConfig
        if ($script:WriteGlobalSkill) {
            Install-Skill (Join-PathMany @($script:PluginDir, "skills", $PluginName)) $script:CodexSkillDir "Codex global skill"
        }
        if ($script:WriteMarketplace) {
            Write-MarketplaceConfig $script:MarketplacePath
            Write-Info "Updated marketplace: $($script:MarketplacePath)"
        }
    }
}

if ($script:InstallClaude) {
    Install-Skill $skillSource $script:ClaudeSkillDir "Claude Code skill"
}

if ($script:InstallOpenCode) {
    if (-not $script:InstallClaude) {
        Install-Skill $skillSource $script:ClaudeSkillDir "OpenCode Claude-compatible skill"
    }
    Update-Guidance $script:OpenCodeAgentsFile (Join-Path $script:ClaudeSkillDir "SKILL.md")
    Write-Info "Updated OpenCode guidance: $($script:OpenCodeAgentsFile)"
}

if ($script:InstallHermes) {
    Install-Skill $skillSource $script:HermesSkillDir "Hermes skill"
    Update-Guidance $script:HermesAgentsFile (Join-Path $script:HermesSkillDir "SKILL.md")
    Write-Info "Updated Hermes guidance: $($script:HermesAgentsFile)"
}

Write-Info "Install complete"
@"

REST runtime:
  REST URL: $($script:RestUrl)

Skill paths:
  $($script:CodexSkillDir)
  $($script:ClaudeSkillDir)
  $($script:HermesSkillDir)

Installation source repo:
  $($script:RepoDir)

PAM-OS uses the REST adapter only.

"@ | Write-Host
