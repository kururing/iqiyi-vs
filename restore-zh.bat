@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Khoi phuc giao dien tieng Trung goc...
net session >nul 2>&1
if not %errorlevel%==0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
py -3 apply-vi.py --restore
if errorlevel 1 python apply-vi.py --restore
echo.
pause
