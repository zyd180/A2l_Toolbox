#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A2L 工具箱 (版本见 utils.config.VERSION, GUI 标题/侧栏/CI Tag 自动引用)
功能1: 地址映射 - 根据 ELF/MAP 文件更新 A2L 变量地址
功能2: 合并A2L - 合并多个 A2L 文件为一个
功能3: 更新A2L - 模型版本同步, 将新版模型 A2L 中的变量/标定量/曲线/MAP 更新进整车 A2L
功能4: 在线标定 - 加载 A2L 和 HEX, 按 FUNCTION 分组编辑标定量; 支持 DCM 导入/导出、HEX 对比、保存 HEX
(DCM 直接写入 HEX 文件由「在线标定」的导入 DCM + 保存 HEX 完成; 引擎函数 dcm_to_hex 保留于 core.dcm_handler)

启动流程: 先出加载屏(纯 tkinter) -> 后台导入界面模块(约 0.5s, 主要是 matplotlib)
-> 主线程构建主窗口 -> 加载屏淡出 / 主窗口淡入.
重导入必须排在加载屏显示之后, 否则加载屏自己也要等那 0.5s 才画得出来.
"""

import sys
import threading
import traceback
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def _resource_path(name):
    """兼容 PyInstaller 打包后的资源路径"""
    base = getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)
    return Path(base) / name


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    ico = _resource_path('app.ico')
    if ico.exists():
        try:
            root.iconbitmap(str(ico))
        except Exception:
            pass

    from gui.splash import SplashScreen
    splash = SplashScreen(root)
    splash.show()
    splash.step('正在加载界面组件…', 35)

    # 界面模块导入放到后台线程: 该链路约 0.5s (matplotlib 占大头), 期间加载屏保持转动
    loaded = {'module': None, 'error': None}

    def _import_ui():
        try:
            import gui.app
            loaded['module'] = gui.app
        except BaseException as exc:        # 导入期任何异常都要返回主线程处理
            loaded['error'] = exc

    def _fail(exc):
        splash.abort()                      # 任何情况下都不留一个一直转圈的窗口
        traceback.print_exc(file=sys.stderr)
        try:
            from tkinter import messagebox
            messagebox.showerror('启动失败', '初始化界面失败:\n%s' % exc)
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    def _reveal():
        """主窗口淡入 (全透明 -> 不透明), 结束后清除 alpha 属性"""
        try:
            root.attributes('-alpha', 0.0)
        except tk.TclError:
            pass
        try:
            root.deiconify()
            root.state('zoomed')
        except tk.TclError:
            pass

        def step(n):
            try:
                if n <= 0:
                    root.attributes('-alpha', 1.0)
                    return
                root.attributes('-alpha', 1.0 - n / 6.0)
                root.after(30, lambda: step(n - 1))
            except tk.TclError:
                pass

        step(6)

    def _poll():
        if loaded['error'] is not None:
            _fail(loaded['error'])
            return
        module = loaded['module']
        if module is None:
            root.after(30, _poll)
            return
        splash.step('构建主窗口…', 90)
        try:
            module.App(root)
        except BaseException as exc:
            _fail(exc)
            return
        splash.step('准备就绪', 100)
        splash.close(on_done=_reveal)

    threading.Thread(target=_import_ui, daemon=True).start()
    root.after(30, _poll)
    root.mainloop()


if __name__ == '__main__':
    main()
