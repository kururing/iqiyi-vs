@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Mo iQIYI va app quan ly phu de AI.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-iqiyi-vi.ps1"
pause
