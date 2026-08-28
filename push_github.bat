@echo off
setlocal
title A2L Toolbox - Push GitHub
cd /d "%~dp0"
echo ========================================
echo   A2L Toolbox - Push GitHub
echo ========================================
echo.
if not exist "%~dp0scripts\push_github.ps1" (
    echo [FAIL] scripts\push_github.ps1 not found
    pause
    exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\push_github.ps1" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
    echo.
    echo [FAIL] GitHub push failed, exit code: %RESULT%
    pause
    exit /b %RESULT%
)
echo.
echo [OK] GitHub push completed.
pause
