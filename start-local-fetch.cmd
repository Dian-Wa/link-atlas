@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local-fetch.ps1" %*
if errorlevel 1 pause
