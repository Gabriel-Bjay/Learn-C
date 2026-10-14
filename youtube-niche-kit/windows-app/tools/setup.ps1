# Work Rewired - one-time setup. Run by double-clicking SETUP.bat.
# Installs everything the video tools need. Safe to run again any time.

$ErrorActionPreference = "Continue"  # check $LASTEXITCODE instead (stderr progress is normal)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($n, $text) { Write-Host ""; Write-Host "[$n/5] $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "      OK - $text" -ForegroundColor Green }
function Fail($text) {
    Write-Host ""
    Write-Host "PROBLEM: $text" -ForegroundColor Red
    Write-Host "Copy everything in this window and send it to Claude for help." -ForegroundColor Yellow
    exit 1
}
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Has-Python312 {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { return $false }
    $v = & py -3.12 --version 2>&1
    return ($LASTEXITCODE -eq 0 -and "$v" -match "3\.12")
}
function Need-Winget {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "winget isn't available on this PC. Install 'App Installer' from the Microsoft Store, then run SETUP again."
    }
}

Write-Host "=== Work Rewired setup ===" -ForegroundColor White
Write-Host "This takes 15-30 minutes the first time (big downloads). Leave this window open."

# 1. Python 3.12 -------------------------------------------------------------
Step 1 "Python 3.12"
if (-not (Has-Python312)) {
    Need-Winget
    Write-Host "      Installing Python 3.12 (Windows may ask for permission - click Yes)..."
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    Refresh-Path
    if (-not (Has-Python312)) { Fail "Python 3.12 didn't install. Restart the PC and double-click SETUP again." }
}
$pyVersion = & py -3.12 --version 2>&1
Ok "$pyVersion"

# 2. FFmpeg (the video engine) ----------------------------------------------
Step 2 "FFmpeg (video engine)"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Need-Winget
    Write-Host "      Installing FFmpeg..."
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    Refresh-Path
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        Fail "FFmpeg didn't install. Restart the PC and double-click SETUP again."
    }
}
Ok "FFmpeg is installed"

# 3. Private Python environment for this folder -------------------------------
Step 3 "Python environment for Work Rewired"
$Py = Join-Path $Root "venv\Scripts\python.exe"
if (Test-Path $Py) {
    # A venv made earlier with another Python version (e.g. 3.14) can't install the voice library.
    $venvVersion = & $Py --version 2>&1
    if ("$venvVersion" -notmatch "3\.12") {
        Write-Host "      The existing venv uses $venvVersion - rebuilding it with Python 3.12..."
        Remove-Item -Recurse -Force (Join-Path $Root "venv")
    }
}
if (-not (Test-Path $Py)) {
    & py -3.12 -m venv (Join-Path $Root "venv")
    if ($LASTEXITCODE -ne 0) { Fail "Couldn't create the Python environment." }
}
Ok "venv folder ready"

# 4. Voice + image libraries --------------------------------------------------
Step 4 "Voice and image libraries (the slow part - several GB)"
& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install "kokoro>=0.9.4" soundfile pillow playwright
if ($LASTEXITCODE -ne 0) { Fail "Library install failed - check your internet connection and run SETUP again." }
Write-Host "      Installing the hidden browser used for automatic screenshots..."
& $Py -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Fail "The screenshot browser didn't install - check your internet connection and run SETUP again." }
Ok "libraries installed"

# 5. Settings: voice + optional Pixabay key -----------------------------------
Step 5 "Settings"
$settings = Join-Path $Root "settings.txt"
if (-not (Test-Path $settings)) {
    "VOICE=am_michael" | Set-Content -Path $settings -Encoding ASCII
}
$keys = Join-Path $Root "keys.txt"
if (Test-Path $keys) {
    Ok "Pixabay key already saved in keys.txt"
} else {
    Write-Host "      Free stock footage: paste your Pixabay API key and press Enter."
    Write-Host "      (Get it at pixabay.com/api/docs while logged in. Or just press Enter to skip.)"
    $key = (Read-Host "      Pixabay key").Trim().Trim('"')
    if ($key) {
        "PIXABAY_API_KEY=$key" | Set-Content -Path $keys -Encoding ASCII
        # Remove any earlier setx attempt so only keys.txt is used.
        [Environment]::SetEnvironmentVariable("PIXABAY_API_KEY", $null, "User")
        Ok "key saved in keys.txt"
    } else {
        Write-Host "      Skipped. You can add it later: create keys.txt with the line PIXABAY_API_KEY=yourkey"
    }
}

# Final check: download the voice model and make voice samples -----------------
Write-Host ""
Write-Host "Final check: downloading the voice model and making voice samples..." -ForegroundColor Cyan
& $Py (Join-Path $Root "tools\voiceover.py") --samples
if ($LASTEXITCODE -ne 0) { Fail "The voice test didn't work." }

Write-Host ""
Write-Host "=== SETUP COMPLETE ===" -ForegroundColor Green
Write-Host "Opening the voice_samples folder - listen and pick a voice."
Write-Host "To change the voice, open settings.txt and change am_michael to another name (e.g. bm_george)."
Write-Host "Next: double-click MAKE-VIDEO.bat"
Start-Process (Join-Path $Root "voice_samples")
