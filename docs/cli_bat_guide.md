# A2L 工具箱命令行 (bat 脚本) 使用指南

适用版本: V2.8.0 起。同一个 `A2L_Toolbox.exe`：**不带参数 = 图形界面；带子命令 = 无界面执行**，
供 bat / 计划任务 / CI 脚本自动化调用。

---

## 1. 必须先懂的三件事

### 1.1 调用必须用 `start /wait`

exe 是"窗口程序"（双击不弹黑窗的那种）。cmd 对窗口程序**默认不等它跑完**就执行下一行，
直接写 `A2L_Toolbox.exe addr ...` 会导致后面的 `%ERRORLEVEL%` 拿不到真实结果。
正确写法固定为：

```bat
start /wait "" "A2L_Toolbox.exe" addr --src VCU.map --in car.a2l --out car_new.a2l
```

- 第一个 `""` 是窗口标题占位，**不能省**（否则带引号的 exe 路径会被当成标题）
- `start /wait` 会等 exe 结束，之后 `%ERRORLEVEL%` 就是 exe 的退出码

### 1.2 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 执行失败（文件不存在、解析出错等；dcm 子命令有超限错误时也为 1） |
| 2 | 参数错误（缺必填参数、参数组合不合法） |

### 1.3 日志输出到哪里

- 从 bat/cmd 调用：日志直接打印在**调用它的窗口**里，不弹新黑窗
- 无控制台环境（如某些计划任务配置）：日志落到**工作目录**的 `A2L_Toolbox_cli.log`
- 输出文件路径以日志最后一行 `输出: ...` 为准

---

## 2. 最小可用模板

把下面内容存成 `run.bat`，放到 `A2L_Toolbox.exe` 同目录，改路径后双击即可。

> **编码要求：含中文的 bat 必须保存为 GBK/ANSI**（记事本"另存为 → 编码 ANSI"）。
> cmd 按系统代码页逐行解析 bat，存成 UTF-8 会把中文行撕碎报"不是内部或外部命令"；
> `chcp 65001` 也救不了（cmd 对 UTF-8 bat 的解析有已知 bug）。

```bat
@echo off
setlocal
rem %~dp0 = 本 bat 所在目录(带反斜杠), 保证 exe 相对 bat 定位, 与双击时的工作目录无关
set TOOLBOX=%~dp0A2L_Toolbox.exe

start /wait "" "%TOOLBOX%" addr --src "%~dp0VCU.map" --in "%~dp0car.a2l" --out "%~dp0car_new.a2l"
set EL=%ERRORLEVEL%
chcp 936 >nul
if %EL% neq 0 (
    echo 执行失败, 退出码 %EL%
    pause
    exit /b %EL%
)
echo 完成
pause
```

要点：
- **所有路径加双引号**，防空格/中文路径被撕开
- 用 `%~dp0` 基于 bat 位置定位文件，不要依赖"当前目录"（双击和计划任务的工作目录可能不同）
- `setlocal` 防止变量污染调用方环境
- **exe 跑完要 `chcp 936 >nul` 恢复代码页**：exe 输出日志时会把控制台切到 UTF-8 (65001)，
  不恢复的话 bat 后续的中文 echo 会乱码；而 `chcp` 会清零 ERRORLEVEL，
  所以必须**先 `set EL=%ERRORLEVEL%` 再 chcp**，之后判断 `%EL%`
- 双击运行时结尾加 `pause`，否则窗口一闪而过看不到任何信息

---

## 3. 四个子命令速查

### 3.1 addr — 地址映射（ELF/MAP → A2L 地址）

```bat
start /wait "" "%TOOLBOX%" addr --src VCU.map --in car.a2l --out car_new.a2l [--remove-unmatched] [--only-missing]
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--src` | 是 | ELF 或 MAP 文件，按扩展名自动识别（`.map` 走 MAP 解析，其余按 ELF） |
| `--in` | 是 | A2L 输入 |
| `--out` | 是 | A2L 输出（不修改输入文件） |
| `--remove-unmatched` | 否 | 删除 A2L 中有、符号表中没有的变量 |
| `--only-missing` | 否 | 仅填补 0x0000 占位，不覆盖已有真实地址（默认全量覆盖） |

### 3.2 merge — 合并多个 A2L

```bat
start /wait "" "%TOOLBOX%" merge --folder .\a2l_dir --out merged.a2l [--header head.a2l] [--map VCU.map] [--no-recursive] [--upd-addr] [--only-missing]
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--folder` | 是 | 输入文件夹（默认含子文件夹） |
| `--out` | 是 | 输出 A2L |
| `--header` | 否 | 头文件 A2L：合并内容插入其 Data 标记处；不给则输出去壳纯内容 |
| `--map` | 否 | 符号归属 MAP：同名对象按"定义它的 SWC"只保留一份 |
| `--no-recursive` | 否 | 不扫描子文件夹 |
| `--upd-addr` | 否 | 合并后按 `--map` 刷新 ECU 地址（**必须同时给 `--map` 且为 .map**） |
| `--only-missing` | 否 | 地址刷新仅填占位 |

### 3.3 sync — 模型版本同步（新版模型 A2L → 整车 A2L）

```bat
start /wait "" "%TOOLBOX%" sync --src model1.a2l model2.a2l --base car.a2l --out car.a2l [--addr VCU.map] [--no-purge] [--no-backup] [--only-missing]
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--src` | 是 | 新版模型 A2L，**空格分隔可写多个**，按顺序依次同步 |
| `--base` | 是 | Base A2L（整车 A2L） |
| `--out` | 是 | 输出 A2L（可与 base 相同，即原地更新） |
| `--addr` | 否 | 同步完成后按此 ELF/MAP 对输出整体刷地址；给 `.map` 时还自动按定义方裁决 |
| `--no-purge` | 否 | 不删除旧版有而新版没有的对象（默认删除） |
| `--no-backup` | 否 | 不生成 .bak 备份（默认备份） |
| `--only-missing` | 否 | 刷地址仅填占位。**往整车追加新模型、MAP 与整车不是同一次构建时强烈建议加** |

### 3.4 dcm — DCM 写入 HEX

```bat
start /wait "" "%TOOLBOX%" dcm --dcm cal.dcm --a2l car.a2l --hex fw.hex --out fw_new.hex
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--dcm` | 是 | DCM 标定文件 |
| `--a2l` | 是 | 描述地址/布局/转换的 A2L |
| `--hex` | 是 | HEX 输入 |
| `--out` | 是 | HEX 输出（不修改原 HEX） |

与 GUI「导入 DCM + 保存 HEX」完全同一条代码路径：超限对象跳过并计入错误（此时退出码 1）。

> 任何子命令的完整参数可用 `start /wait "" "%TOOLBOX%" addr -h` 查看；
> `start /wait "" "%TOOLBOX%" --version` 查看版本号。

---

## 4. 实用脚本示例

### 4.1 批量地址映射（for 循环 + 延迟扩展）

对文件夹里每个 A2L 用同一份 MAP 刷地址，输出到 `out\` 子目录：

```bat
@echo off
setlocal EnableDelayedExpansion
set TOOLBOX=%~dp0A2L_Toolbox.exe
set MAP=%~dp0VCU.map
if not exist "%~dp0out" mkdir "%~dp0out"

for %%f in ("%~dp0a2l_in\*.a2l") do (
    echo 处理 %%~nxf ...
    start /wait "" "%TOOLBOX%" addr --src "%MAP%" --in "%%~f" --out "%~dp0out\%%~nxf" --only-missing
    set EL=!ERRORLEVEL!
    chcp 936 >nul
    if !EL! neq 0 (
        echo [失败] %%~nxf 退出码 !EL!
        exit /b 1
    )
)
echo 全部完成
```

**注意**：
- for/括号块里读退出码必须用 `!EL!` 延迟扩展——`%ERRORLEVEL%` 在整段括号解析时
  就被展开成旧值，是 bat 最常见的坑
- 循环体里每次 exe 调用后同样要 `set EL=!ERRORLEVEL!` + `chcp 936 >nul`（原因见 §2）
- 通配集带引号时用 `%%~f` 取去掉引号的路径再自行加引号，最稳妥

### 4.2 流水线：合并 → 同步 → 刷地址

```bat
@echo off
setlocal
set TOOLBOX=%~dp0A2L_Toolbox.exe
set WORK=%~dp0work

start /wait "" "%TOOLBOX%" merge --folder "%~dp0models" --out "%WORK%\merged.a2l" --map "%~dp0VCU.map"
set EL=%ERRORLEVEL%
chcp 936 >nul
if %EL% neq 0 exit /b 1

start /wait "" "%TOOLBOX%" sync --src "%WORK%\merged.a2l" --base "%~dp0car.a2l" --out "%WORK%\car_synced.a2l" --addr "%~dp0VCU.map" --only-missing
set EL=%ERRORLEVEL%
chcp 936 >nul
if %EL% neq 0 exit /b 1

echo 流水线完成, 产物: %WORK%\car_synced.a2l
```

### 4.3 失败重试一次

```bat
start /wait "" "%TOOLBOX%" addr --src "%MAP%" --in "%IN%" --out "%OUT%"
set EL=%ERRORLEVEL%
chcp 936 >nul
if %EL% neq 0 (
    echo 首次失败, 重试...
    start /wait "" "%TOOLBOX%" addr --src "%MAP%" --in "%IN%" --out "%OUT%"
    set EL=%ERRORLEVEL%
    chcp 936 >nul
    if %EL% neq 0 exit /b 1
)
```

---

## 5. 常见问题

**Q: 为什么我的 bat 一闪而过 / 拿不到退出码？**
没用 `start /wait`。窗口程序不阻塞 cmd，必须 `start /wait ""` 调用。

**Q: 日志中文乱码 / bat 报"不是内部或外部命令"？**
两种乱码要分开治：
- bat 自身的中文被撕碎 → bat 存成了 UTF-8，改存 **GBK/ANSI**（见 §2）
- exe 跑完后 bat 的中文 echo 乱码 → exe 把控制台切到了 UTF-8，
  调用后 `chcp 936 >nul` 恢复（先存退出码再 chcp，见 §2）
- exe 自己的日志始终按 UTF-8 输出，控制台窗口里正常显示，无需处理

**Q: 计划任务里跑，看不到日志？**
无控制台环境下日志写到**工作目录**的 `A2L_Toolbox_cli.log`。计划任务里把
"起始于(工作目录)"设成固定目录，或直接重定向：
`start /wait "" "%TOOLBOX%" addr ... > "%~dp0run.log" 2>&1`
（有重定向时输出走文件，不再依赖控制台）。

**Q: 双击 bat 正常，资源管理器里直接给 exe 传参却看不到输出？**
那种场景没有父控制台，日志落到 exe 工作目录的 `A2L_Toolbox_cli.log`。
日常请始终通过 bat/cmd 调用。

**Q: `--out` 和 `--in` 可以是同一个文件吗？**
可以（原地更新）。sync 默认先生成 `.bak` 备份；addr/merge 不备份，原地覆盖前请自行留底。

**Q: 源码方式调用？**
装了 Python 依赖后等价可用：`python main.py addr --src ...`（参数完全一致，
此时无需 `start /wait`，`python` 本身是控制台程序）。

---

## 6. 现成文件

- `cli_example.bat`（仓库根目录）：四个功能各一段的可运行示例
- 本文档：`docs/cli_bat_guide.md`