# Work Rewired - make a video. Run by double-clicking MAKE-VIDEO.bat.
# Asks which video and whether you want a quick preview or the final 1080p file.

param([switch]$NoUpdate)

$ErrorActionPreference = "Continue"  # check $LASTEXITCODE instead (stderr progress is normal)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Get the latest tools first. If this script itself was updated, restart with the new one.
$updater = Join-Path $PSScriptRoot "update.ps1"
if (-not $NoUpdate -and (Test-Path $updater)) {
    $before = (Get-FileHash -LiteralPath $PSCommandPath).Hash
    & $updater -Auto
    if ((Get-FileHash -LiteralPath $PSCommandPath).Hash -ne $before) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -NoUpdate
        exit $LASTEXITCODE
    }
}

function Fail($text) {
    Write-Host ""
    Write-Host "PROBLEM: $text" -ForegroundColor Red
    Write-Host "Copy everything in this window and send it to Claude for help." -ForegroundColor Yellow
    exit 1
}
function Read-Settings($path) {
    if (Test-Path $path) {
        foreach ($line in Get-Content $path) {
            if ($line -match '^\s*([A-Za-z_]+)\s*=\s*(.+?)\s*$') { Set-Item -Path ("env:" + $Matches[1].ToUpper()) -Value $Matches[2] }
        }
    }
}
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

$Py = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Fail "Setup hasn't been run yet. Double-click SETUP.bat first." }
Refresh-Path

# Ignore any broken key from an earlier setx attempt, then load keys.txt + settings.txt.
if ($env:PIXABAY_API_KEY -match 'paste|\.\.\.|"') { Remove-Item env:PIXABAY_API_KEY }
Read-Settings (Join-Path $Root "keys.txt")
Read-Settings (Join-Path $Root "settings.txt")
$Voice = if ($env:VOICE) { $env:VOICE } else { "am_michael" }

# 1. Which video? ---------------------------------------------------------------
$videos = @(Get-ChildItem (Join-Path $Root "videos") -Directory | Sort-Object Name)
if ($videos.Count -eq 0) { Fail "No video folders found inside the videos folder." }
Write-Host "Videos:" -ForegroundColor Cyan
for ($i = 0; $i -lt $videos.Count; $i++) { Write-Host ("  {0}. {1}" -f ($i + 1), $videos[$i].Name) }
$pick = Read-Host "Which video? Type the number and press Enter"
if (-not ($pick -match '^\d+$') -or [int]$pick -lt 1 -or [int]$pick -gt $videos.Count) { Fail "'$pick' isn't one of the numbers above." }
$dir = $videos[[int]$pick - 1].FullName

$script = Join-Path $dir "script.txt"
$shots = Join-Path $dir "shots.txt"
$wav = Join-Path $dir "script.wav"
$thumbSpec = Join-Path $dir "thumbnail.txt"

function Make-Thumbnails {
    if (-not (Test-Path $thumbSpec)) {
        Write-Host "No thumbnail.txt in this folder - skipping thumbnails (in your Claude Project, type: THUMB)." -ForegroundColor Yellow
        return $false
    }
    Write-Host ""
    Write-Host "Making thumbnails..." -ForegroundColor Cyan
    & $Py (Join-Path $Root "tools\thumbnail.py") $thumbSpec | Out-Host  # show output; keep it out of the return value
    if ($LASTEXITCODE -ne 0) { Fail "The thumbnail step failed (see the message above)." }
    return $true
}

# 2. Preview, final or thumbnails? ------------------------------------------------
Write-Host ""
Write-Host "  1. Quick preview  (small, fast - to check timing and see what's missing)"
Write-Host "  2. Final video    (full 1080p for YouTube - takes 10-20 minutes)"
Write-Host "  3. Thumbnails only (a few seconds)"
$choice = Read-Host "Type 1, 2 or 3 and press Enter"
if ($choice -eq "3") {
    if (Make-Thumbnails) {
        Write-Host ""
        Write-Host "=== DONE ===" -ForegroundColor Green
        $first = Join-Path $dir "thumbnail-1.jpg"
        if (Test-Path $first) { Start-Process $first }
    }
    exit 0
}
$isFinal = $choice -eq "2"
if (-not (Test-Path $script)) { Fail "There's no script.txt in $dir" }
if (-not (Test-Path $shots)) { Fail "There's no shots.txt in $dir" }

# 3. Voiceover (only if the script is new or changed) ----------------------------
$needVoice = (-not (Test-Path $wav)) -or ((Get-Item $script).LastWriteTime -gt (Get-Item $wav).LastWriteTime)
if ($needVoice) {
    Write-Host ""
    Write-Host "Making the voiceover with voice '$Voice'..." -ForegroundColor Cyan
    & $Py (Join-Path $Root "tools\voiceover.py") $script --voice $Voice
    if ($LASTEXITCODE -ne 0) { Fail "The voiceover step failed (see the message above)." }
} else {
    Write-Host ""
    Write-Host "Voiceover is up to date - skipping." -ForegroundColor Green
}

# 4. Build the video ----------------------------------------------------------------
Write-Host ""
Write-Host "Building the video..." -ForegroundColor Cyan
$mvArgs = @($wav, $shots)
if (-not $isFinal) { $mvArgs += "--preview" }
$music = Get-ChildItem $dir -Filter *.mp3 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($music) { $mvArgs += @("--music", $music.FullName); Write-Host "Using music: $($music.Name)" }
& $Py (Join-Path $Root "tools\make_video.py") @mvArgs
if ($LASTEXITCODE -ne 0) { Fail "The video build failed (see the message above)." }
$null = Make-Thumbnails

$out = Join-Path $dir ($(if ($isFinal) { "script.mp4" } else { "script_preview.mp4" }))
Write-Host ""
Write-Host "=== DONE ===" -ForegroundColor Green
Write-Host "Video: $out"
if ($isFinal) { Write-Host "Captions for YouTube: $(Join-Path $dir 'script.srt')" }
if (Test-Path (Join-Path $dir "thumbnail-1.jpg")) { Write-Host "Thumbnails: $dir\thumbnail-1.jpg (and -2, -3 for YouTube's Test & Compare)" }
Start-Process $out
