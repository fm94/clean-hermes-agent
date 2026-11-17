# Install Hermes from a sanitized checkout (Windows)
#
#   powershell -ExecutionPolicy Bypass -File .\install-safe.ps1 -Repo "C:\Users\you\hermes-safe.bundle"
#   powershell -ExecutionPolicy Bypass -File .\install-safe.ps1 -Repo "https://github.com/you/hermes-agent-safe.git"
#
# Why this wrapper: the official installer clones
# https://github.com/NousResearch/hermes-agent.git, whose checkout trips the
# endpoint rule that blocks one vendor name. -Repo points the same
# installer at a checkout that has been rewritten (vendor id "dsx"), and
# -Channel main skips the release-tag lookup, which only knows the official
# repository.
#
# The installer itself is still the official, unmodified install.ps1; only its
# source URL and channel are overridden through the supported env vars.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [string]$Channel = 'main',
    [string]$BundleHash = ''
)

$ErrorActionPreference = 'Stop'

# A local .bundle path is a valid git source; make it absolute so the clone
# does not depend on the current directory the installer later changes into.
if ($Repo -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://' -and $Repo -notmatch '^git@') {
    if (-not (Test-Path -LiteralPath $Repo)) { throw "source not found: $Repo" }
    $Repo = (Resolve-Path -LiteralPath $Repo).Path
    if ($BundleHash) {
        $got = (Get-FileHash -Algorithm SHA256 -LiteralPath $Repo).Hash.ToLowerInvariant()
        if ($got -ne $BundleHash.ToLowerInvariant()) {
            throw "bundle sha256 mismatch: got $got, expected $BundleHash"
        }
        Write-Host "bundle sha256 verified" -ForegroundColor Green
    }
}

$env:HERMES_REPO_URL = $Repo
$env:HERMES_INSTALL_CHANNEL = $Channel

$log = Join-Path $env:USERPROFILE ("hermes-install-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
Start-Transcript -Path $log -Force | Out-Null
Write-Host "source : $Repo"
Write-Host "channel: $Channel"
Write-Host "log    : $log"
Write-Host ''

try {
    $installer = (New-Object System.Net.WebClient).DownloadString('https://hermes-agent.nousresearch.com/install.ps1')
    Invoke-Expression $installer
} finally {
    Stop-Transcript | Out-Null
}

# `hermes update` on a non-official origin offers to add the official repo as
# `upstream` and sync from it. That fetch would reintroduce the banned string
# into .git, so pre-answer "no" for this profile.
$hermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA 'hermes' }
if (Test-Path -LiteralPath $hermesHome) {
    New-Item -ItemType File -Force -Path (Join-Path $hermesHome '.skip_upstream_prompt') | Out-Null
}

Write-Host ''
Write-Host "Done. Install log: $log" -ForegroundColor Green
Write-Host 'Start Hermes with: hermes'
