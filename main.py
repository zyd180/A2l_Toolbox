#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
A2L 工具箱 v1.9.2
功能1: 地址映射 - 根据 ELF/MAP 文件更新 A2L 变量地址
功能2: 合并A2L - 合并多个 A2L 文件为一个
功能3: 更新A2L - 模型版本同步, 将新版模型 A2L 中的变量/标定量/曲线/MAP 更新进整车 A2L
功能4: 在线标定 - 加载 A2L 和 HEX, 按 FUNCTION 分组编辑标定量; 支持 DCM 导入/导出、HEX 对比、保存 HEX
(DCM 直接写入 HEX 文件由「在线标定」的导入 DCM + 保存 HEX 完成; 引擎函数 dcm_to_hex 保留于 core.dcm_handler)
"""

import sys
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
    from gui.app import App
    
    root = tk.Tk()
    ico = _resource_path('app.ico')
    if ico.exists():
        try:
            root.iconbitmap(str(ico))
        except Exception:
            pass
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()