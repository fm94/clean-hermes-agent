# Collect the evidence needed to explain an install failure on Windows.
#
#   powershell -ExecutionPolicy Bypass -File .\diagnose.ps1
#
# Read-only except for a throwaway virtualenv under %TEMP%\hermes-uv-probe.
# Writes a single log next to your user profile; nothing secret is captured
# (no tokens, no config values -- only whether the variables are set).
# Note: the blocked vendor string must not appear in this file either.

param([switch]$SkipNetwork)

$ErrorActionPreference = 'Continue'
$log = Join-Path $env:USERPROFILE ("hermes-diag-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

function Section([string]$Title) {
    "`n===== $Title =====" | Tee-Object -FilePath $log -Append
}
function Line([string]$Text) {
    $Text | Tee-Object -FilePath $log -Append
}
function Probe([string]$Label, [scriptblock]$Body) {
    Line "-- $Label"
    try { & $Body 2>&1 | ForEach-Object { "   $_" } | Tee-Object -FilePath $log -Append }
    catch { "   EXCEPTION: $($_.Exception.GetType().Name): $($_.Exception.Message)" | Tee-Object -FilePath $log -Append }
}

"hermes install diagnostics  $(Get-Date -Format o)" | Set-Content -Path $log

Section 'Host'
Line ("OS        : " + (Get-CimInstance Win32_OperatingSystem).Caption + " " + [Environment]::OSVersion.Version)
Line ("Arch      : " + $env:PROCESSOR_ARCHITECTURE + " / " + (Get-CimInstance Win32_ComputerSystem).SystemType)
Line ("PowerShell: " + $PSVersionTable.PSVersion)
Line ("User      : " + $env:USERNAME)
Line ("HOME      : " + $env:USERPROFILE)
Line ("LONG PATHS: " + (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled)
try {
    $drive = Get-PSDrive ($env:USERPROFILE.Substring(0,1)) -ErrorAction Stop
    Line ("Free disk : " + [math]::Round($drive.Free / 1GB, 1) + " GB")
} catch { Line "Free disk : unknown" }

Section 'Environment (presence only)'
foreach ($name in @('HTTP_PROXY','HTTPS_PROXY','NO_PROXY','ALL_PROXY','SSL_CERT_FILE','REQUESTS_CA_BUNDLE','CURL_CA_BUNDLE','UV_CACHE_DIR','UV_PYTHON','UV_PYTHON_INSTALL_DIR','UV_LINK_MODE','UV_INDEX_URL','UV_DEFAULT_INDEX','PIP_INDEX_URL','HERMES_HOME','HERMES_RUNTIME_DIR','HERMES_REPO_URL','HERMES_INSTALL_CHANNEL')) {
    $v = [Environment]::GetEnvironmentVariable($name)
    if ($v) { Line ("{0,-24} = {1}" -f $name, $v) }
}

Section 'Security products'
Probe 'services' {
    Get-Service -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'Falcon|CSFalcon|SentinelOne|CrowdStrike|Defender|Sense' } |
        Select-Object Name, Status, DisplayName | Format-Table -AutoSize | Out-String
}
Probe 'defender' {
    Get-MpComputerStatus -ErrorAction Stop |
        Select-Object AMRunningMode, RealTimeProtectionEnabled, AntivirusEnabled | Format-List | Out-String
}
Probe 'falcon filter driver' {
    & fltmc.exe filters 2>&1 | Select-String -Pattern 'Falcon|csagent|WdFilter'
}

Section 'Network'
if ($SkipNetwork) { Line 'skipped' } else {
    foreach ($target in @('pypi.org','files.pythonhosted.org','github.com','objects.githubusercontent.com','astral.sh','hermes-agent.nousresearch.com')) {
        Probe "dns+tcp $target" {
            $ips = [Net.Dns]::GetHostAddresses($target) | ForEach-Object { $_.IPAddressToString }
            "dns: " + ($ips -join ', ')
            $client = New-Object Net.Sockets.TcpClient
            $iar = $client.BeginConnect($target, 443, $null, $null)
            if (-not $iar.AsyncWaitHandle.WaitOne(4000)) { "tcp 443: TIMEOUT"; $client.Close(); return }
            $client.EndConnect($iar); "tcp 443: ok"; $client.Close()
        }
    }
    foreach ($url in @('https://pypi.org/simple/certifi/','https://files.pythonhosted.org/')) {
        Probe "https $url" {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 25 -MaximumRedirection 3
            "status: $($r.StatusCode)  bytes: $($r.RawContentLength)"
        }
    }
}

Section 'Write access'
Probe 'temp' {
    $p = Join-Path $env:TEMP ("hermes-write-{0}.tmp" -f (Get-Random))
    Set-Content -Path $p -Value 'ok'; "wrote $p"; Remove-Item $p -Force
}
Probe 'uv cache' {
    $cache = if ($env:UV_CACHE_DIR) { $env:UV_CACHE_DIR } else { Join-Path $env:LOCALAPPDATA 'uv\cache' }
    New-Item -ItemType Directory -Force -Path $cache | Out-Null
    $p = Join-Path $cache ("hermes-write-{0}.tmp" -f (Get-Random))
    Set-Content -Path $p -Value 'ok'; "wrote $p"; Remove-Item $p -Force
}
Probe 'install dir' {
    $dir = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA 'hermes' }
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $p = Join-Path $dir ("hermes-write-{0}.tmp" -f (Get-Random))
    Set-Content -Path $p -Value 'ok'; "wrote $p"; Remove-Item $p -Force
}

Section 'uv'
$uv = Get-Command uv -ErrorAction SilentlyContinue
Line ("on PATH   : " + $(if ($uv) { $uv.Source } else { 'no' }))
Probe 'version' { & uv --version }
Probe 'python list' { & uv python list 2>&1 | Select-Object -First 15 }
$store = Join-Path $env:LOCALAPPDATA 'hermes\tools'
if (Test-Path $store) {
    $pinned = Get-ChildItem -Path $store -Filter 'uv-*' -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pinned) {
        $exe = Join-Path $pinned.FullName 'uv.exe'
        Line ("pm-store  : $exe")
        if (Test-Path $exe) { Probe 'pm-store version' { & $exe --version } }
    }
}
$probe = Join-Path $env:TEMP 'hermes-uv-probe'
Probe 'create venv (downloads python if missing)' {
    if (Test-Path $probe) { Remove-Item $probe -Recurse -Force }
    & uv venv $probe --python 3.14 2>&1
}
Probe 'install one wheel' {
    & uv pip install --python (Join-Path $probe 'Scripts\python.exe') --verbose certifi 2>&1 | Select-Object -Last 30
}

Section 'Installed checkout (if any)'
$hermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA 'hermes' }
$checkout = Join-Path $hermesHome 'hermes-agent'
if (Test-Path (Join-Path $checkout '.git')) {
    Line ("path: $checkout")
    Probe 'head' { & git -C $checkout log -1 --format='%H %s' }
    Probe 'remotes' { & git -C $checkout remote -v }
    Probe 'status' { & git -C $checkout status --porcelain=v1 -b | Select-Object -First 10 }
} else {
    Line 'no checkout found'
}

"`nLog written to $log" | Tee-Object -FilePath $log -Append
Write-Host "`nSend this file back: $log" -ForegroundColor Cyan
