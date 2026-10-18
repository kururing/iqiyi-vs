@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Mo Youku kem Vietsub.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-youku-vi.ps1"
