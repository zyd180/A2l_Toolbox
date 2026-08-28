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
│   ├── app.py               # 主窗口类
│   └── calib/               # 在线标定页签 (对标 INCA)
│       ├── tab.py           # 页签主界面 (分组树/搜索/表格)
│       ├── editors.py       # VALUE/CURVE/MAP/轴点 编辑器
│       └── widgets.py       # CellGrid 可编辑色阶网格控件
├── core/                    # 核心功能模块
│   ├── __init__.py
│   ├── elf_parser.py        # ELF 解析
│   ├── map_parser.py        # MAP 解析
│   ├── a2l_parser.py        # A2L 解析
│   ├── dcm_handler.py       # DCM 解析 + A2L 索引构建
│   ├── hex_handler.py       # HEX 文件处理 + 编码
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
└── test/                    # 测试数据
```

## 使用方法

### GUI 模式

```bash
python main.py
```

GUI 启动时默认最大化；日志区固定在窗口底部，支持折叠，并可拖动日志区顶部边缘调整高度。

### 打包为 EXE

```
build.bat
```

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
5. 可选勾选"包含子文件夹"
6. 点击"开始合并"

### 模型版本同步操作流程

1. 切换到「更新A2L」标签页
2. 添加一个或多个新版模型 A2L（支持多选）
3. 选择 Base A2L（整车 A2L）和输出路径
4. 可选勾选"删除旧版有而新版没有的对象"（完全以新版为准）
5. 可选勾选"备份目标文件"（生成 .bak 备份）
6. 可选勾选"同步完成后自动更新地址"并选择 ELF/MAP 地址文件——对输出整体刷新地址，一步完成"合成 + 刷新地址"
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
