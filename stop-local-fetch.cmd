@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-local-fetch.ps1" %*
if errorlevel 1 pause
