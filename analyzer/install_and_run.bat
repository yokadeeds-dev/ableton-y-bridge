@echo off
REM Copyright (C) 2026 Yoka
REM SPDX-License-Identifier: AGPL-3.0-only
REM Installation and startup script for audio analyzer
REM This script installs required packages and starts the audio analyzer

setlocal enabledelayedexpansion

if not defined PYTHON_EXE set PYTHON_EXE=python
set SCRIPT_DIR=%~dp0
set REQUIREMENTS=%SCRIPT_DIR%requirements.txt
set ANALYZER_SCRIPT=%SCRIPT_DIR%audio_analyzer.py

echo.
echo ========================================
echo Audio Analyzer - Setup and Run
echo ========================================
echo.

REM Check if Python executable exists
if not exist "%PYTHON_EXE%" (
    echo ERROR: Python executable not found at:
    echo   %PYTHON_EXE%
    echo.
    echo Please install Python 3.11 or update the path in this script.
    pause
    exit /b 1
)

echo Python found: %PYTHON_EXE%
echo.

REM Install requirements
echo Installing required packages...
echo.
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto :error

"%PYTHON_EXE%" -m pip install -r "%REQUIREMENTS%"
if errorlevel 1 goto :error

echo.
echo Installation complete!
echo.
echo ========================================
echo Starting Audio Analyzer
echo ========================================
echo.
echo The analyzer will:
echo  1. Search for WASAPI loopback audio input
echo  2. Capture system audio (what Ableton is playing)
echo  3. Perform real-time analysis
echo  4. Send JSON data to localhost:7878 every 200ms
echo.
echo To monitor the data, open another command prompt and run:
echo   python "%SCRIPT_DIR%udp_receiver_test.py"
echo.
echo Press Ctrl+C in this window to stop the analyzer.
echo.
pause

REM Run the analyzer
"%PYTHON_EXE%" "%ANALYZER_SCRIPT%"
goto :end

:error
echo.
echo ERROR: Installation failed!
echo Please check the error messages above.
pause
exit /b 1

:end
echo.
echo Audio analyzer stopped.
pause
exit /b 0
