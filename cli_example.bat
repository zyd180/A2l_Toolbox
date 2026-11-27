@echo off
rem ============================================================
rem A2L 工具箱命令行调用示例
rem 注意: 本文件必须保存为 GBK/ANSI 编码 (cmd 按系统代码页解析 bat,
rem       存成 UTF-8 会把中文行撕碎); 用记事本另存为时选 ANSI
rem - exe 不带参数 = GUI; 带子命令 = 无界面执行, 日志打印到本窗口
rem - 窗口程序必须用 start /wait 等待结束, 才能拿到退出码
rem - 退出码: 0 成功 / 1 执行失败 / 2 参数错误
rem 用法: 把下面示例路径改成你的真实文件后运行 (双击或 cmd 里跑均可)
rem 详细编写指南: docs\cli_bat_guide.md
rem ============================================================
setlocal

rem ---- 定位 exe: 优先 bat 同目录 (发布布局), 其次 dist\ (源码仓库布局) ----
set TOOLBOX=%~dp0A2L_Toolbox.exe
if not exist "%TOOLBOX%" set TOOLBOX=%~dp0dist\A2L_Toolbox.exe
if not exist "%TOOLBOX%" (
    echo [错误] 找不到 A2L_Toolbox.exe, 请把本 bat 放到 exe 同目录
    pause
    exit /b 2
)

rem ---- 示例输入检查: 下面用的是占位路径, 请先改成真实文件 ----
if not exist "%~dp0VCU.map" (
    echo [提示] 示例路径 VCU.map / car.a2l 不存在。
    echo        请编辑本 bat, 把 --src / --in / --out 改成你的真实文件路径,
    echo        或把 VCU.map 和 car.a2l 放到本 bat 同目录后再运行。
    pause
    exit /b 2
)

rem ---- 功能1: 地址映射 (ELF/MAP 按扩展名自动识别) ----
rem exe 输出时会把控制台切到 UTF-8, 跑完用 chcp 936 恢复, 否则后续中文乱码;
rem chcp 会清零 ERRORLEVEL, 所以先存到 EL
start /wait "" "%TOOLBOX%" addr --src "%~dp0VCU.map" --in "%~dp0car.a2l" --out "%~dp0car_new.a2l" --only-missing
set EL=%ERRORLEVEL%
chcp 936 >nul
if %EL% neq 0 goto :fail

rem ---- 功能2: 合并 A2L (可选头文件/归属MAP/合并后刷地址) ----
rem start /wait "" "%TOOLBOX%" merge --folder "%~dp0a2l_dir" --out "%~dp0merged.a2l" --map "%~dp0VCU.map" --upd-addr
rem set EL=%ERRORLEVEL%
rem chcp 936 >nul
rem if %EL% neq 0 goto :fail

rem ---- 功能3: 模型版本同步 (多模型 + 同步后刷地址) ----
rem start /wait "" "%TOOLBOX%" sync --src "%~dp0model1.a2l" "%~dp0model2.a2l" --base "%~dp0car.a2l" --out "%~dp0car.a2l" --addr "%~dp0VCU.map" --only-missing
rem set EL=%ERRORLEVEL%
rem chcp 936 >nul
rem if %EL% neq 0 goto :fail

rem ---- 功能4: DCM 写入 HEX ----
rem start /wait "" "%TOOLBOX%" dcm --dcm "%~dp0cal.dcm" --a2l "%~dp0car.a2l" --hex "%~dp0fw.hex" --out "%~dp0fw_new.hex"
rem set EL=%ERRORLEVEL%
rem chcp 936 >nul
rem if %EL% neq 0 goto :fail

echo.
echo 全部完成
pause
exit /b 0

:fail
echo.
echo 执行失败, 退出码 %EL% (1=执行失败 2=参数错误)
pause
exit /b %EL%