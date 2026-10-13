@echo off
title Work Rewired - Make video
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\make.ps1" %*
echo.
pause
