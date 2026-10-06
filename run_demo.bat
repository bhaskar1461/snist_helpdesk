@echo off
title SNIST Help Desk - Standalone Offline Demo
echo =====================================================================
echo    Launching SNIST Help Desk Standalone Demo (No DB or setup needed)
echo =====================================================================
echo.
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.9 or higher from https://www.python.org/
    echo and ensure "Add Python to PATH" is checked during installation.
    echo.
    pause
    exit /b 1
)

python run_demo.py %*
if errorlevel 1 (
    echo.
    echo [!] An error occurred while running the demo.
    pause
)
