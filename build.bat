@echo off
chcp 437 >nul 2>&1

echo =================================
echo    A2L Toolbox - Build Script
echo =================================

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.7+
    pause
    exit /b 1
)

echo.
echo [1/2] Checking PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller
    pause
    exit /b 1
)

echo.
echo [2/2] Building EXE...
pyinstaller A2L_Toolbox.spec
if errorlevel 1 (
    echo [ERROR] Build failed
    pause
    exit /b 1
)

echo.
echo =================================
echo    Build Success: dist\A2L_Toolbox.exe
echo =================================
pause
