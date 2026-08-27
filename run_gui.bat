@echo off
rem A2L Toolbox 启动器: 失败时错误可见, 不再静默
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"D:\Tools\Python\python.exe" -u main.py > "%TEMP%\a2l_toolbox_run.log" 2>&1
if errorlevel 1 (
    echo.
    echo [启动失败] 错误日志如下 (%TEMP%\a2l_toolbox_run.log^):
    echo --------------------------------------------------
    type "%TEMP%\a2l_toolbox_run.log"
    echo --------------------------------------------------
    pause
)
