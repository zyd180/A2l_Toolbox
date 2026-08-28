#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GUI 主窗口 - 纯壳: 横幅 / 左侧大导航(SideNav) / 内容栈 / 全局按钮 / 日志坞 / 状态栏.

导航结构:
  大Tab0 "A2L处理"   → 横向子 Notebook (地址映射/合并A2L/更新A2L, 布局如旧)
  大Tab1 "在线标定"   → CalibTab 自包含页签
业务逻辑全部在各页签模块 (gui/tabs/*); 本文件只负责组装与全局服务.
"""

import threading
import traceback
import webbrowser

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    print('错误: 无法导入 tkinter')
    raise SystemExit(1)

from gui.theme import COLORS, FONT, STATUS_STYLES, setup_style
from gui.common.logdock import LogDock
from gui.common.sidenav import SideNav
from gui.tabs.registry import A2L_TABS, CALIB_TAB
from utils.config import VERSION
from utils import appstate


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f'A2L 工具箱 {VERSION}')
        self.root.geometry('900x700')
        self.root.minsize(780, 540)
        self.root.state('zoomed')
        self.root.configure(bg=COLORS['bg'])

        self.nav_index = 0
        self._setup_style()
        self._build_ui()
        self._bind_keys()

    # ---------- 样式 / 界面 ----------
    def _setup_style(self):
        setup_style(self.root)

    def _build_ui(self):
        main = tk.Frame(self.root, bg=COLORS['bg'])
        main.pack(fill='both', expand=True)

        # === 顶部横幅 ===
        header = tk.Frame(main, bg=COLORS['header'])
        header.pack(fill='x')
        inner = tk.Frame(header, bg=COLORS['header'])
        inner.pack(fill='x', padx=16, pady=10)
        ttk.Label(inner, text='A2L 工具箱', style='HeaderTitle.TLabel').pack(side='left')
        ttk.Label(inner, text=VERSION, style='HeaderSub.TLabel').pack(
            side='left', padx=(8, 0), pady=(8, 0))
        link = ttk.Label(inner, text='GitHub: https://github.com/zyd180',
                         style='HeaderLink.TLabel')
        link.pack(side='right')
        link.bind('<Button-1>', lambda e: webbrowser.open('https://github.com/zyd180'))
        ttk.Label(inner, text='开发者: Henry', style='HeaderSub.TLabel').pack(
            side='right', padx=(0, 14))

        # === 底部状态栏 ===
        self.status_var = tk.StringVar(value='  就绪')
        self.status_bar = tk.Label(main, textvariable=self.status_var, anchor='w',
                                   bg=COLORS['ready_bg'], fg='#374151',
                                   font=FONT['body'], padx=8, pady=3)
        self.status_bar.pack(side='bottom', fill='x')

        body = tk.Frame(main, bg=COLORS['bg'])
        body.pack(fill='both', expand=True, padx=12, pady=(8, 8))

        # === 左侧大导航 ===
        self.sidenav = SideNav(body, on_select=self._on_nav, width=170)
        self.sidenav.pack(side='left', fill='y', padx=(0, 8))

        # === 右侧内容区 ===
        right = tk.Frame(body, bg=COLORS['bg'])
        right.pack(side='left', fill='both', expand=True)

        # 页0: A2L处理 → 横向子 Notebook (布局如旧)
        self.sub_notebook = ttk.Notebook(right)
        self.a2l_tabs = [cls(self.sub_notebook, app=self) for cls in A2L_TABS]
        self.sub_notebook.bind('<<NotebookTabChanged>>', self._on_sub_change)

        # 页1: 在线标定 (自包含)
        self.calib_tab = CALIB_TAB(right, app=self)

        # === 日志坞 ===
        self.logdock = LogDock(right)
        self.logdock.pack(side='bottom', fill='x', expand=False, pady=(4, 0))
        self.log = self.logdock.text
        self.log_buffer = self.logdock.buffer
        self.log_queue = self.logdock.queue

        # === 操作按钮区 ===
        self.action_bar = ttk.Frame(right, style='Card.TFrame', padding=(0, 6, 0, 0))
        self.run_btn = ttk.Button(self.action_bar, text='开始', style='Primary.TButton',
                                  command=self.start_processing)
        self.run_btn.pack(side='left')
        self.test_btn = ttk.Button(self.action_bar, text='测试解析',
                                   command=self.test_active)
        ttk.Button(self.action_bar, text='保存日志', style='Tool.TButton',
                   command=self.save_log).pack(side='right', padx=(8, 0))
        ttk.Button(self.action_bar, text='清空日志', style='Tool.TButton',
                   command=self.clear_log).pack(side='right')
        self.action_bar.pack(side='bottom', fill='x')

        # === 进度条 (运行时显示) ===
        self.progress = ttk.Progressbar(right, mode='indeterminate',
                                        style='Accent.Horizontal.TProgressbar')

        # --- 恢复上次导航 ---
        st = appstate.load_app_state()
        nav = 0 if int(st.get('last_nav', 0) or 0) == 0 else 1
        sub = int(st.get('last_sub', 0) or 0)
        sub = max(0, min(sub, len(self.a2l_tabs) - 1))
        self.sub_notebook.select(sub)
        self.sidenav.add('A2L处理', '地址/合并/同步')
        self.sidenav.add('在线标定', 'INCA 风格')
        self.sidenav.select(nav)

    # ---------- 导航路由 ----------
    def _on_nav(self, i):
        self.nav_index = i
        if i == 0:
            self.calib_tab.pack_forget()
            self.sub_notebook.pack(fill='both', expand=True, before=self.logdock)
        else:
            self.sub_notebook.pack_forget()
            self.calib_tab.pack(fill='both', expand=True, before=self.logdock)
        appstate.save_app_state(last_nav=i)
        self._sync_buttons()
        self.clear_log()
        self.status('ready', 'A2L处理' if i == 0 else '在线标定')

    def _on_sub_change(self, event=None):
        try:
            sub = self.sub_notebook.index(self.sub_notebook.select())
        except tk.TclError:
            return
        appstate.save_app_state(last_sub=sub)
        self._sync_buttons()
        self.clear_log()
        self.status('ready', self.a2l_tabs[sub].TITLE.strip())

    @property
    def active_tab(self):
        if self.nav_index == 0:
            return self.a2l_tabs[self.sub_notebook.index(self.sub_notebook.select())]
        return self.calib_tab

    def _sync_buttons(self):
        tab = self.active_tab
        show = self.nav_index == 0 and tab.HAS_RUN
        if show:
            self.run_btn.pack(side='left')
            self.run_btn.config(text=tab.RUN_LABEL)
        else:
            self.run_btn.pack_forget()
        if self.nav_index == 0 and tab.HAS_TEST:
            self.test_btn.pack(side='left', padx=(8, 0))
        else:
            self.test_btn.pack_forget()

    def start_processing(self):
        tab = self.active_tab
        if self.nav_index == 0 and tab.HAS_RUN:
            tab.start()

    def test_active(self):
        tab = self.active_tab
        if self.nav_index == 0 and tab.HAS_TEST:
            tab.test()

    # ---------- 运行态 / 状态栏 ----------
    def begin_running(self):
        self.run_btn.config(state='disabled')
        self.test_btn.config(state='disabled')
        self.progress.pack(fill='x', pady=(0, 4), before=self.logdock)
        self.progress.start(12)
        self.status('running', '处理中, 请稍候...')

    def end_running(self):
        # 线程结束前先把队列中未渲染的日志刷出, 避免弹窗先于日志显示
        self.logdock.flush()
        self.progress.stop()
        self.progress.pack_forget()
        self.run_btn.config(state='normal')
        self.test_btn.config(state='normal')

    def status(self, level, text):
        """状态栏 (带颜色): ready/running/ok/err; 线程安全."""
        if not self._on_main():
            self.root.after(0, self.status, level, text)
            return
        bg, fg = STATUS_STYLES.get(level, STATUS_STYLES['ready'])
        self.status_var.set('  ' + text)
        self.status_bar.config(bg=bg, fg=fg)

    _status = status    # 兼容旧调用名

    # ---------- 线程安全弹窗 ----------
    def _on_main(self):
        return threading.current_thread() is threading.main_thread()

    def info(self, title, msg):
        if not self._on_main():
            self.root.after(0, self.info, title, msg)
            return
        self.logdock.flush()
        messagebox.showinfo(title, msg)

    def error(self, title, msg):
        if not self._on_main():
            self.root.after(0, self.error, title, msg)
            return
        self.logdock.flush()
        messagebox.showerror(title, msg)

    # ---------- 日志委托 ----------
    def log_msg(self, msg):
        self.logdock.log_msg(msg)

    def clear_log(self):
        self.logdock.clear()

    def save_log(self):
        self.logdock.save()

    # ---------- 快捷键 ----------
    def _bind_keys(self):
        # F5 运行; Ctrl+1..3 → A2L处理+对应子Tab; Ctrl+4 → 在线标定
        self.root.bind('<F5>', lambda e: self.start_processing())
        for i in range(len(self.a2l_tabs)):
            self.root.bind('<Control-Key-%d>' % (i + 1),
                           lambda e, i=i: self._goto(i))
        self.root.bind('<Control-Key-4>', lambda e: self._goto_calib())

    def _goto(self, sub):
        if self.nav_index == 0:
            try:
                if self.sub_notebook.index(self.sub_notebook.select()) == sub:
                    return
            except tk.TclError:
                pass
        self.sub_notebook.select(sub)
        self._on_nav(0)

    def _goto_calib(self):
        if self.nav_index == 1:
            return
        self._on_nav(1)
