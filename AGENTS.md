# AGENTS.md — A2L Toolbox 工程约定

## 构建 / 运行 / 测试

- 运行: `python main.py` (或 `run_gui.bat`, 失败时自动打印日志)
- 编译检查: `python -m py_compile` 全部 .py
- 打包: `pyinstaller A2L_Toolbox.spec`
- GUI 回归脚本模式: 必须用 `root.mainloop()` + `after` 调度,
  **禁止** `withdraw()` 后裸 `update()` 轮询 (焦点/尺寸断言会假失败,
  且工作线程首次 `after()` 可能崩溃); 需要键盘事件断言时对目标控件
  `focus_force()` 后 `event_generate`, Tk 键盘事件只投递给焦点窗口

## 危险操作黑名单 (有前科!)

- **严禁** 用 PowerShell 5.1 的 `Get-Content | Set-Content` 管道改源码:
  PS5.1 对无 BOM UTF-8 按 GBK 误读, 回写即永久损坏中文
  (2026-08-27 曾因此损坏 3 个源文件, 靠 PyInstaller PYZ 快照 + pyc 常量
  真值表才救回)。改源码一律用 Edit/Write 工具或 python (显式 utf-8)
- PS 5.1 不支持 `&&`; 用 `;` + `if ($?)`
- 内联 `python -c "..."` 含引号/中文时会被 PS 撕碎 — 落盘 .py 文件再执行

## 架构

- `gui/app.py` = 纯壳 (横幅/侧边导航/内容栈/按钮/状态栏/运行态服务), 不写业务
- 导航: `SideNav` 大 Tab ("A2L处理"=子Notebook 3页 / "在线标定"=CalibTab 整页);
  active_tab 属性负责路由, 全局按钮由 BaseTab 契约驱动
- 页签 = `gui/tabs/*` 的 BaseTab 子类; A2L_TABS/CALIB_TAB 见 registry
  - 契约: TITLE/DESC/HAS_RUN/RUN_LABEL/HAS_TEST + build()/start()/test()
  - 自包含页签 (在线标定) 用 HAS_RUN=False; BaseTab 对 Notebook 容器自动 add 页签
- 视觉参数只允许引用 `gui/theme.py` 的 COLORS/SPACE/FONT
- 线程安全: 工作线程经 `app.log_msg`(队列批量渲染) / `app.root.after` 回主线程
