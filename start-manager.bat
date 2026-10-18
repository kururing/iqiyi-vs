@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Khoi dong app quan ly phu de AI (http://127.0.0.1:18766/)...
echo Dong cua so nay se tat app. Giu cua so nay mo trong khi su dung.
"%~dp0.venv\Scripts\python.exe" "%~dp0subtitle_app.py"
pause
