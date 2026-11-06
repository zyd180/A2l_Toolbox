# A2L 工具箱

汽车电子 ECU 开发中用于 A2L (ASAP2) 文件处理的桌面工具。

## 关于作者

- **开发者**: Henry
- **邮箱**: [1378099981@qq.com]
- **GitHub**: https://github.com/zyd180

## 功能

### 1. 根据 ELF/MAP 文件更新 A2L 变量地址

解析 ELF（32/64位）或 MAP 文件提取符号表，按变量名精确匹配 A2L 中的 CHARACTERISTIC、MEASUREMENT、AXIS_PTS 块，更新其 ECU_ADDRESS 字段。

### 2. 合并多个 A2L 文件

从文件夹中提取所有 A2L 文件的 RECORD_LAYOUT、变量定义和 COMPU_METHOD，按源文件生成 FUNCTION 分组。

支持两种输出模式：
- **指定头文件 A2L**：将提取的内容插入头文件的 `/* *** Data *** */` 标记处，生成完整的 A2L
- **不指定头文件**：输出去壳的纯内容（RECORD_LAYOUT + 变量 + COMPU_METHOD + FUNCTION）

### 3. 模型版本同步（更新A2L）

将一个或多个新版模型 A2L（如 Simulink Coder 生成）中的变量、标定量、曲线、MAP 等对象同步进整车 A2L。

主要特性：
- 智能替换：同名对象用新版内容更新，同时保留整车 A2L 中已有的真实 ECU 地址（0x0000 占位符不覆盖真实地址）
- 多模型支持：可同时添加多个新版模型 A2L，各模型归属独立判定、互不干扰
- 新增对象自动插入目标中该模型原有数据区域之后
- FUNCTION 块同步：同名 FUNCTION 以新版为准整体更新，目标没有的 FUNCTION 新增
- 可选"删除旧版遗留对象"：旧版有而新版没有的对象安全删除（按 COMPU_METHOD 前缀/引用归属判定），删除前检查块外残留引用
- 可选目标文件自动备份 (.bak)
- GROUP 块不再同步/保留：合并时跳过源文件的全部 GROUP，清理时属于该模型的旧 GROUP 一并删除

### 4. DCM 写入 HEX

解析 DCM 标定文件 (KONSERVIERUNG_FORMAT)，结合 A2L 的 ECU 地址/记录布局/转换公式将物理值编码为原始字节，按地址写入 Intel HEX 并输出新文件（不修改原 HEX）。

支持的对象类型：
- 标定量/块（FESTWERT / FESTWERTEBLOCK）
- 曲线（GRUPPENKENNLINIE / FESTKENNLINIE）
- MAP（GRUPPENKENNFELD），含 COM_AXIS 轴数据写入
- 轴（STUETZSTELLENVERTEILUNG）

编码特性：
- RAT_FUNC 按系数正向求值编码（Simulink 生成的 COEFFS 为 phys→raw 方向）
- 支持 FLOAT32/FLOAT64 直接打包
- 字节序默认小端，遵循 COMPU_METHOD 显式声明
- 支持 FIX_AXIS 隐式轴（轴不占 ECU 存储，只写数值区）
- 逐条校验和验证，输出保持 32 字节数据记录与扩展线性地址记录风格

### 5. 在线标定

加载 A2L 和 HEX 文件，对标 INCA 的在线标定工作台。

主要特性：
- 三种分组浏览：FUNCTION / GROUP / 平铺，左侧树形导航
- 实时搜索：输入即过滤，支持 `*` `?` 通配符；可勾选"仅显示已修改"
- 四类编辑器：
  - 标定值 (VALUE)：Spinbox + 滑块，限值范围约束
  - 曲线 (CURVE)：matplotlib 折线预览 + 表格编辑，X 轴点联动写回 AXIS_PTS
  - MAP：matplotlib 热图 + INCA 风格色阶网格
  - 轴点 (AXIS_PTS) 独立编辑器
- Excel 互通复制粘贴 (TSV)、选区线性插值、行/列填充
- 单元格级修改跟踪（脏标记高亮）、单对象还原、Undo/Redo (Ctrl+Z/Y)
- 写入限值保护；保存 HEX 前自动备份 .bak
- 数据集管理：
  - **导出 DCM**：全部或仅已修改对象，含轴值/单位/长标识
  - **导入 DCM**：应用到当前会话（含轴点联动），整体一个撤销单元
  - **HEX 对比**：与任意 HEX 逐字节对比，按对象统计改动并输出报告
- 轴点 (AXIS_PTS) 对象与标定量混合列出，可直接搜索和编辑
- 最近使用的 A2L/HEX 路径与分组模式自动记忆

## 环境要求

- Python 3.7+
- matplotlib (在线标定的曲线/MAP 图形预览; 未安装时自动降级为纯表格模式): `pip install -r requirements.txt`

## 文件结构

```
A2l_Toolbox/
├── main.py                  # 程序入口
├── gui/                     # GUI 模块
│   ├── __init__.py
│   ├── app.py               # 主窗口壳 (横幅/侧导航/内容栈/全局按钮/日志坞/状态栏)
│   ├── theme.py             # 设计令牌 (色板/间距/字号) + ttk 样式工厂
│   ├── common/              # 通用件
│   │   ├── logdock.py       # 日志坞 (线程安全队列渲染/着色/折叠/导出)
│   │   ├── sidenav.py       # 左侧大卡片导航
│   │   └── widgets.py       # 文件行 / 路径列表
│   └── tabs/                # 页签
│       ├── base.py          # BaseTab 契约 (TITLE/DESC/HAS_RUN/RUN_LABEL/HAS_TEST)
│       ├── registry.py      # 页签注册表
│       ├── addr.py          # 地址映射
│       ├── merge.py         # 合并 A2L
│       ├── sync.py          # 更新 A2L (模型版本同步)
│       └── calib/           # 在线标定页签 (对标 INCA)
│           ├── tab.py       # 页签主界面 (分组树/搜索/表格)
│           ├── editors.py   # VALUE/CURVE/MAP/轴点 编辑器
│           └── widgets.py   # CellGrid 可编辑色阶网格控件
├── core/                    # 核心功能模块
│   ├── __init__.py
│   ├── elf_parser.py        # ELF 解析
│   ├── map_parser.py        # MAP 解析
│   ├── a2l_parser.py        # A2L 解析
│   ├── dcm_handler.py       # DCM 解析 + DCM 批量写入 HEX (基于 CalibSession)
│   ├── hex_handler.py       # HEX 读写 + 标定值写入编码
│   ├── calib_engine.py      # 在线标定引擎 (CalibSession)
│   └── sync_engine.py       # 模型版本同步
├── utils/                   # 工具模块
│   ├── __init__.py
│   ├── config.py            # 配置管理 (版本、配色、文件类型)
│   └── logger.py            # 日志工具
├── requirements.txt         # 依赖 (matplotlib)
├── A2L_Toolbox.spec         # PyInstaller 打包配置
├── app.ico                  # 程序图标
├── build.bat                # PyInstaller 打包脚本
├── CHANGELOG.md             # 更新日志
├── README.md                # 本文件
└── test/                    # 测试
    ├── regress/             # 自动化回归 (入库, CI 执行)
    │   ├── fixtures.py      # 合成夹具: A2L + HEX (不依赖真机样本)
    │   ├── _harness.py      # 极简断言框架 (不引入 pytest)
    │   ├── test_hex_format.py    # HEX 读写/INCA 记录格式/值编码
    │   ├── test_calib_engine.py  # COEFFS 方向/轴/存储方向/撤销/DCM 往返
    │   ├── test_a2l_tools.py     # 地址映射/合并/模型同步
    │   ├── test_gui_contract.py  # 页签契约 + 在线标定运行态
    │   ├── run_all.py       # 入口: python test/regress/run_all.py
    │   └── run_one.py       # 单模块调试用
    └── (样本数据)            # 真机 A2L/HEX/DCM/ELF, 不入库 (.gitignore)
```

## 回归测试

```bash
python test/regress/run_all.py     # 全部; 退出码 0=通过
python test/regress/run_one.py test_calib_engine   # 单模块
```

用例全部基于 `fixtures.py` 现场合成的 A2L+HEX（小夹具），不依赖 `test/` 下的真机样本，
因此 CI 与本地行为一致。覆盖点均为历史上真实出过问题的地方：COEFFS 方向（Simulink
phys→raw）、字节序声明、MAP 的 `COLUMN_DIR` 存储方向、FIX_AXIS 隐式轴、段内 0xFF 填充、
同名对象同步时保留整车真实地址、以及在线标定加载的运行态。


## 使用方法

### GUI 模式

```bash
python main.py
```

GUI 启动时默认最大化；日志区固定在窗口底部，支持折叠，并可拖动日志区顶部边缘调整高度。

启动时先显示加载屏（旋转动画 + 阶段文字），界面模块加载完成后淡出、主窗口淡入；
启动失败会关闭加载屏并弹出错误框，不会留一个一直转圈的窗口。

> 注意：EXE 为 onefile 单文件，双击后前约 3 秒是 PyInstaller 解包（此时加载屏还没出来）。
> 这段空白与本工具有关的唯一解法是改用 onedir 目录形式发布（实测主窗口就绪 4.4s → 1.6s），
> 但产物会从"一个 exe"变成"exe + _internal 目录"。
### 打包为 EXE

```
build.bat
```

### CI

GitHub Actions 配置位于 `.github/workflows/ci.yml`，在 Windows runner 上执行 Python 3.10/3.11/3.12 编译与导入检查、Tk GUI 冒烟测试和 PyInstaller 打包校验。主分支构建成功后会按 `utils/config.py` 中的版本号创建 Tag 并发布 EXE 压缩包。

### 一键推送 GitHub

双击 `push_github.bat`，或执行 `powershell -File scripts/push_github.ps1`。脚本会校验远程仓库为 `zyd180/A2l_Toolbox`，自动提交本地改动，并使用 `--force` 让本地分支覆盖远程分支；本地 `.rar` 交付压缩包不会被自动提交。可使用 `-DryRun` 只检查远程和分支，不执行提交或推送。

### 地址映射操作流程

1. 切换到「地址映射」标签页
2. 选择符号源类型：ELF 或 MAP
3. 选择符号源文件（ELF/MAP）、A2L 输入文件和 A2L 输出文件
4. 可选勾选"删除未匹配变量"（移除 A2L 中存在但符号表中没有的变量）
5. 点击"开始更新"

### 合并 A2L 操作流程

1. 切换到「合并A2L」标签页
2. 选择包含 A2L 文件的文件夹
3. 指定输出文件路径
4. （可选）选择头文件 A2L — 合并内容将插入该文件的 Data 区域
5. （可选）选择「符号归属MAP」— 同名对象按 MAP 中符号的定义模块判定归哪个 SWC，
   只保留定义方那一份（不给则按名称前缀/限值启发式裁决，冲突写入 `<输出>_dedup.txt`）
6. （可选）勾选「合并后更新 ECU 地址」— 用同一份 MAP 把 0x0000 占位填成真实地址
   （只填空位，不改写已有地址）
7. 可选勾选"包含子文件夹"
8. 点击"开始合并"

### 模型版本同步操作流程

1. 切换到「更新A2L」标签页
2. 添加一个或多个新版模型 A2L（支持多选）
3. 选择 Base A2L（整车 A2L）和输出路径
4. 可选勾选"删除旧版有而新版没有的对象"（完全以新版为准）
   - 勾选后按"定义该对象的模块"判断归属（依据第 6 步选的 MAP）：属于本模型、但新版
     已不再声明的一律删除，连它引用的旧 GROUP 与旧 COMPU_METHOD 一并清理；
     MAP 显示由**别的模型**定义的对象一个都不动
   - 只给了 ELF（无归属信息）时退回"按 CM 名称前缀"判断，模型内部子系统改过名就会漏删，
     此时以日志里的"删除 0 个"为信号，改用 MAP
5. 可选勾选"备份目标文件"（生成 .bak 备份）
6. 可选勾选"同步完成后自动更新地址"并选择 ELF/MAP 地址文件——对输出整体刷新地址，
   一步完成"合成 + 刷新地址"
   - 建议保留默认的「仅填补 0x0000 占位，不覆盖已有真实地址」：往整车 A2L 追加新模型时，
     若所用 MAP 与整车 A2L 不是同一次构建，全量刷新会把已有地址整体改写
     （实测：4 个模型同步后，安全模式只填 1435 个新对象、改动 0 个已有地址；
     全量刷新会改写 39107 个）
   - **地址文件选 `.map` 时还会自动按"定义方"裁决**：若某对象在 MAP 里由别的模型定义、
     而整车 A2L 已有它，本模型只是引用方，则不覆盖（避免用引用方的 255 兜底把定义方的
     真实限值放宽）。选 ELF 时无归属信息，退回"同名即覆盖"
7. 点击"开始同步"

### DCM 写入 HEX 操作流程 (v1.9.2 起并入「在线标定」)

1. 切换到「在线标定」标签页
2. 选择 A2L 文件和 HEX 文件，点击"加载标定量"
3. 点击"导入 DCM"选择 DCM 文件（含限值校验，整体一个撤销单元）
4. 确认无误后点击"保存 HEX"输出新文件（自动 .bak 备份）
5. 可选：导入前用"HEX 对比"确认基线，导入后再次对比验证写入结果

### 在线标定操作流程

1. 切换到「在线标定」标签页
2. 选择 A2L 文件和 HEX 文件
3. 点击"加载标定量"
4. 左侧树按 FUNCTION 分组显示标定量，右侧表格显示详细信息
5. 使用搜索框搜索标定量（支持 `*` 通配符，如 `ABM_*`）
6. 双击表格中的标定量可修改值
7. 点击"保存 HEX"将修改后的值写入 HEX 文件

## 头文件 A2L 说明

头文件 A2L 是包含完整 A2L 外壳结构的模板文件（ASAP2_VERSION → PROJECT → HEADER → MODULE → A2ML → MOD_PAR → MOD_COMMON → IF_DATA 等）。

合并工具会：
1. 从头文件中保留 Data 注释标记之前的所有内容
2. 提取的 RECORD_LAYOUT、变量定义、COMPU_METHOD、FUNCTION 插入到 Data 标记之后
3. 最后追加 `/end MODULE` 和 `/end PROJECT` 闭合标签

头文件中的标记格式：
```
/* * * * * * * * * * * * * * * Data * * * * * * * * * * * * * * */
```

合并后的内容将替换此标记之后到文件尾的所有内容。

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。
