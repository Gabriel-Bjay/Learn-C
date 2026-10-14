# Work Rewired Studio - run by double-clicking STUDIO.bat (or the desktop shortcut).
# Gets the latest tools, then opens Studio in your browser at http://localhost:8765

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Py = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "PROBLEM: Setup hasn't been run yet. Double-click SETUP.bat first." -ForegroundColor Red
    exit 1
}
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [Environment]::GetEnvironmentVariable("Path", "User")

$updater = Join-Path $PSScriptRoot "update.ps1"
if (Test-Path $updater) { & $updater -Auto }

# One-time: a desktop shortcut so Studio opens like an app.
try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $link = Join-Path $desktop "Work Rewired Studio.lnk"
    if ($desktop -and -not (Test-Path $link)) {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($link)
        $shortcut.TargetPath = Join-Path $Root "STUDIO.bat"
        $shortcut.WorkingDirectory = $Root
        $shortcut.Description = "Work Rewired Studio"
        $shortcut.Save()
        Write-Host "Added a 'Work Rewired Studio' shortcut to your desktop." -ForegroundColor Green
    }
} catch {}

& $Py (Join-Path $PSScriptRoot "studio.py")
