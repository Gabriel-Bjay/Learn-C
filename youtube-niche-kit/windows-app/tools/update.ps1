# Work Rewired - get the latest tools from GitHub. Run by double-clicking UPDATE.bat.
# MAKE-VIDEO.bat also runs this automatically (with -Auto) before every video.
# Never touches keys.txt, settings.txt, venv, screenshots, stock clips, music or finished videos.
# If you edited a file in a video folder (e.g. shots.txt), yours is kept and the new
# version is saved next to it as shots.NEW.txt.

param([switch]$Auto)

$ErrorActionPreference = "Continue"  # check $LASTEXITCODE instead (stderr progress is normal)
$ProgressPreference = "SilentlyContinue"  # PowerShell 5's progress bar makes downloads very slow
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {}

$Repo = "Gabriel-Bjay/Learn-C"
$Branch = "claude/busy-fermat-yzuoe7"
$Root = Split-Path -Parent $PSScriptRoot
$VersionFile = Join-Path $PSScriptRoot "version.txt"
$LibsFile = Join-Path $PSScriptRoot "libs.txt"
$DeliveredFile = Join-Path $PSScriptRoot "delivered.txt"  # last version sent of each file

function Say($text, $color = "Gray") { Write-Host $text -ForegroundColor $color }
function Stop-Update($text) {
    if ($Auto) { Say "Update skipped: $text" "DarkYellow"; Say ""; exit 0 }
    Say ""
    Say "PROBLEM: $text" "Red"
    Say "Copy everything in this window and send it to Claude for help." "Yellow"
    exit 1
}
function Local-Path($rel) { Join-Path $Root ($rel -replace '/', [IO.Path]::DirectorySeparatorChar) }
function Hash-Of($path) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return "" }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLower()
}
function Download($url, $out) {
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $out -TimeoutSec 120 -ErrorAction Stop
}

if (-not (Test-Path (Join-Path $Root "videos"))) {
    Stop-Update "update.ps1 must be in the tools folder inside WorkRewired (it's in $PSScriptRoot)."
}
if (-not $Auto) { Write-Host "=== Work Rewired update ===" -ForegroundColor White }
Say "Checking GitHub for updates..." "Cyan"

# Pin every download to the newest commit so all files come from the same version.
if ($env:WR_UPDATE_BASE) {
    $Base = $env:WR_UPDATE_BASE.TrimEnd('/')
} else {
    $ref = $Branch
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -ErrorAction Stop `
            -Uri "https://api.github.com/repos/$Repo/commits/$Branch" -Headers @{ Accept = "application/vnd.github.sha" }
        $sha = $r.Content
        if ($sha -is [byte[]]) { $sha = [Text.Encoding]::ASCII.GetString($sha) }
        if ("$sha".Trim() -match '^[0-9a-f]{40}$') { $ref = "$sha".Trim() }
    } catch {}
    $Base = "https://raw.githubusercontent.com/$Repo/$ref/youtube-niche-kit"
}

$Tmp = Join-Path ([IO.Path]::GetTempPath()) ("wr-update-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $Tmp -Force | Out-Null
try {
    # 1. What the newest version contains -----------------------------------------------
    $manifestPath = Join-Path $Tmp "manifest.txt"
    try { Download "$Base/windows-app/manifest.txt" $manifestPath }
    catch { Stop-Update "couldn't reach GitHub ($($_.Exception.Message)). Check your internet and try again." }

    $version = ""; $pip = ""; $browser = ""; $files = @()
    foreach ($line in Get-Content -LiteralPath $manifestPath) {
        $f = $line -split "`t"
        if ($f[0] -eq "VERSION") { $version = $f[1] }
        elseif ($f[0] -eq "PIP") { $pip = $f[1] }
        elseif ($f[0] -eq "BROWSER") { $browser = $f[1] }
        elseif ($f[0] -eq "FILE" -and $f.Count -ge 6) {
            $old = @(); if ($f[5] -ne "-") { $old = @($f[5] -split ",") }
            $files += [pscustomobject]@{ Mode = $f[1]; Hash = $f[2]; Src = $f[3]; Dest = $f[4]; Old = $old }
        }
    }
    if (-not $version -or $files.Count -eq 0) { Stop-Update "the update list on GitHub looks broken - try again later." }

    $haveVersion = ""; if (Test-Path $VersionFile) { $haveVersion = "$(Get-Content $VersionFile -Raw)".Trim() }
    $haveLibs = ""; if (Test-Path $LibsFile) { $haveLibs = "$(Get-Content $LibsFile -Raw)".Trim() }
    $wantLibs = "$pip | $browser"
    if ($Auto -and $haveVersion -eq $version -and $haveLibs -eq $wantLibs) {
        Say "Tools are up to date." "Green"; Say ""; exit 0
    }

    # 2. Which files changed ----------------------------------------------------------------
    $delivered = @{}
    if (Test-Path $DeliveredFile) {
        foreach ($line in Get-Content $DeliveredFile) {
            $d = $line -split "`t"
            if ($d.Count -eq 2) { $delivered[$d[0]] = $d[1] }
        }
    }
    $plan = @()
    foreach ($f in $files) {
        $dest = Local-Path $f.Dest
        $local = Hash-Of $dest
        if ($local -eq $f.Hash) { continue }
        if ($f.Mode -eq "user" -and $local -and -not ($f.Old -contains $local)) {
            # The user changed this file: keep theirs, and put a new version of ours next to it
            # (once - not again if they edited it after we last sent it).
            if ($delivered[$f.Dest] -eq $f.Hash) { continue }
            $name = [IO.Path]::GetFileNameWithoutExtension($dest) + ".NEW" + [IO.Path]::GetExtension($dest)
            $target = Join-Path (Split-Path -Parent $dest) $name
            $plan += [pscustomobject]@{ File = $f; Target = $target; Kept = $true }
        } else {
            $plan += [pscustomobject]@{ File = $f; Target = $dest; Kept = $false }
        }
    }

    # 3. Download everything first, check it, then copy into place ---------------------------
    $i = 0
    foreach ($p in $plan) {
        $i++
        $p | Add-Member -NotePropertyName Temp -NotePropertyValue (Join-Path $Tmp "file$i")
        Say ("  downloading {0}" -f $p.File.Dest)
        try { Download "$Base/$($p.File.Src)" $p.Temp }
        catch { Stop-Update "couldn't download $($p.File.Dest) ($($_.Exception.Message)). Try again." }
        if ((Hash-Of $p.Temp) -ne $p.File.Hash) {
            Stop-Update "GitHub sent an out-of-date copy of $($p.File.Dest). Wait 5 minutes and try again."
        }
    }
    foreach ($p in $plan) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $p.Target) -Force | Out-Null
        Copy-Item -LiteralPath $p.Temp -Destination $p.Target -Force -ErrorAction Stop
    }

    # 4. New libraries, if the tools need any ------------------------------------------------
    if ($haveLibs -ne $wantLibs) {
        $Py = if ($env:WR_PYTHON) { $env:WR_PYTHON } else { Join-Path $Root "venv\Scripts\python.exe" }
        if (Test-Path $Py) {
            Say "Installing/updating libraries (a few minutes the first time)..." "Cyan"
            & $Py -m pip install --quiet --disable-pip-version-check @($pip -split ' ')
            if ($LASTEXITCODE -ne 0) { Stop-Update "the library install failed - check your internet and run UPDATE.bat again." }
            if ($browser) {
                & $Py -m playwright install $browser
                if ($LASTEXITCODE -ne 0) { Stop-Update "the screenshot browser didn't install - run UPDATE.bat again." }
            }
            Set-Content -Path $LibsFile -Value $wantLibs -Encoding ASCII
        } else {
            Say "Libraries: not installed yet - double-click SETUP.bat first." "Yellow"
        }
    }
    foreach ($f in $files) { $delivered[$f.Dest] = $f.Hash }
    Set-Content -Path $DeliveredFile -Encoding ASCII -Value @($delivered.Keys | Sort-Object | ForEach-Object { "$_`t$($delivered[$_])" })
    Set-Content -Path $VersionFile -Value $version -Encoding ASCII

    # 5. Report --------------------------------------------------------------------------------
    $updated = @($plan | Where-Object { -not $_.Kept })
    $kept = @($plan | Where-Object { $_.Kept })
    if ($plan.Count -eq 0) {
        Say "Everything is up to date." "Green"
    } else {
        if ($updated.Count -gt 0) {
            Say "Updated:" "Green"
            foreach ($p in $updated) { Say "  $($p.File.Dest)" }
        }
        foreach ($p in $kept) {
            Say ""
            Say "You've edited $($p.File.Dest), so your copy was kept." "Yellow"
            Say "  The new version is next to it: $(Split-Path -Leaf $p.Target)" "Yellow"
            Say "  To use the new one: delete yours and rename the .NEW file." "Yellow"
        }
    }
    Say ""
} finally {
    Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
