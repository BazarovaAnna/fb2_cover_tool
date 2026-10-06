@echo off
chcp 65001 > nul

where py >nul 2>nul
if %errorlevel%==0 (
    py fb2_covers.py
) else (
    python fb2_covers.py
)

pause
