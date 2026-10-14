@echo off
title Work Rewired Studio
rem Everything is inside one bracketed block so cmd reads it all before running:
rem the updater can then safely replace this file while it is running.
(
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\studio.ps1"
  echo.
  pause
  exit /b
)
