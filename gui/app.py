#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GUI 主窗口 - 纯壳: 横幅 / 窄条导航 / 中央内容 / 右停靠面板(结果+日志) / 状态栏.

V2.7.0 工作台化布局:
  左   SideNav 窄条 (64px)
  中央 A2L处理 = 横向子 Notebook (地址映射/合并A2L/更新A2L) | 在线标定 = CalibTab
  右   停靠面板 (PanedWindow 可拖宽/可折叠/持久化):
       「结果」页 = ResultPanel 结构化结果卡片 (替代完成弹窗, 常驻可回看)
       「日志」页 = LogDock (过程流, 不再挤压主内容区)
  底部 状态栏 (进度条并入, 不再单独占一行)

业务逻辑全部在各页签模块 (gui/tabs/*); 本文件只负责组装与全局服务.
对外 API 保持: log_msg/clear_log/save_log/log_buffer/log_queue/
begin_running/end_running/status/info/error/active_tab.
新增: show_result(...) 供页签推送结果卡片 (阶段2 页签接入).
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

from gui.theme import COLORS, FONT, STATUS_STYLES, DIVIDER, setup_style
from gui.common.logdock import LogDock
from gui.common.sidenav import SideNav
from gui.common.resultpanel import ResultPanel
from gui.tabs.registry import A2L_TABS, CALIB_TAB
from utils.config import VERSION
from utils import appstate

_DOCK_DEFAULT_W = 320
_DOCK_MIN_W = 220


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f'A2L 工具箱 {VERSION}')
        self.root.geometry('900x700')
        self.root.minsize(860, 540)
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
        inner.pack(fill='x', padx=16, pady=8)
        ttk.Label(inner, text='A2L 工具箱', style='HeaderTitle.TLabel').pack(side='left')
        ttk.Label(inner, text=VERSION, style='HeaderSub.TLabel').pack(
            side='left', padx=(8, 0), pady=(6, 0))
        link = ttk.Label(inner, text='GitHub: https://github.com/zyd180',
                         style='HeaderLink.TLabel')
        link.pack(side='right')
        link.bind('<Button-1>', lambda e: webbrowser.open('https://github.com/zyd180'))
        ttk.Label(inner, text='开发者: Henry', style='HeaderSub.TLabel').pack(
            side='right', padx=(0, 14))

        # === 底部状态栏 (进度条并入) ===
        self.status_frame = tk.Frame(main, bg=COLORS['ready_bg'])
        self.status_frame.pack(side='bottom', fill='x')
        self.progress = ttk.Progressbar(self.status_frame, mode='indeterminate',
                                        style='Accent.Horizontal.TProgressbar',
                                        length=150)
        # 折叠后重新展开停靠面板的小按钮 (藏于状态栏右侧)
        self.dock_restore_btn = tk.Label(
            self.status_frame, text='◂ 面板', bg=COLORS['ready_bg'],
            fg=COLORS['primary_dark'], font=FONT['bold'], cursor='hand2', padx=8)
        self.dock_restore_btn.bind('<Button-1>', lambda e: self._toggle_dock())
        self.status_var = tk.StringVar(value='  就绪')
        self.status_bar = tk.Label(self.status_frame, textvariable=self.status_var,
                                   anchor='w', bg=COLORS['ready_bg'], fg='#374151',
                                   font=FONT['body'], padx=8, pady=3)
        self.status_bar.pack(side='left', fill='x', expand=True)

        # === 主体: 窄导航 + PanedWindow(中央 | 右停靠面板) ===
        body = tk.Frame(main, bg=COLORS['bg'])
        body.pack(fill='both', expand=True, padx=8, pady=(8, 4))

        self.sidenav = SideNav(body, on_select=self._on_nav, width=64)
        self.sidenav.pack(side='left', fill='y', padx=(0, 6))

        self.paned = tk.PanedWindow(body, orient='horizontal', bd=0,
                                    sashwidth=4, sashrelief='flat', bg=DIVIDER)
        self.paned.pack(side='left', fill='both', expand=True)

        # --- 中央列 (动作按钮在各页签页脚, 见 BaseTab) ---
        self.center = tk.Frame(self.paned, bg=COLORS['bg'])

        # 页0: A2L处理 → 横向子 Notebook
        self.sub_notebook = ttk.Notebook(self.center)
        self.a2l_tabs = [cls(self.sub_notebook, app=self) for cls in A2L_TABS]
        self.sub_notebook.bind('<<NotebookTabChanged>>', self._on_sub_change)

        # --- 右停靠面板 (先于 CalibTab 构建: 详情页容器由 CalibTab 填充) ---
        self._build_dock()

        # 页1: 在线标定 (自包含)
        self.calib_tab = CALIB_TAB(self.center, app=self)

        # 导航注册与恢复
        self.sidenav.add('A2L处理', '')
        self.sidenav.add('在线标定', '')
        st = appstate.load_app_state()
        nav = 0 if int(st.get('last_nav', 0) or 0) == 0 else 1
        sub = max(0, min(int(st.get('last_sub', 0) or 0), len(self.a2l_tabs) - 1))
        self.sub_notebook.select(sub)
        self.sidenav.select(nav)

        # 停靠面板状态恢复 (宽度需等首次布局后设置)
        if int(st.get('dock_collapsed', 0) or 0):
            self._toggle_dock(force_collapsed=True)
        try:
            dock_w = max(_DOCK_MIN_W, int(st.get('dock_width', 0) or _DOCK_DEFAULT_W))
        except (TypeError, ValueError):
            dock_w = _DOCK_DEFAULT_W
        self.root.after_idle(lambda: self._apply_dock_width(dock_w))
        self.paned.bind('<ButtonRelease-1>', lambda e: self._save_dock_width())
        self.select_dock_tab(int(st.get('dock_tab', 1) or 1))

    def _build_dock(self):
        """右停靠面板: 标题行(收起按钮) + Notebook(结果/日志)."""
        st = appstate.load_app_state()
        try:
            dock_w = max(_DOCK_MIN_W, int(st.get('dock_width', 0) or _DOCK_DEFAULT_W))
        except (TypeError, ValueError):
            dock_w = _DOCK_DEFAULT_W
        self.dock = tk.Frame(self.paned, bg=COLORS['card'], width=dock_w)
        self.dock.pack_propagate(False)

        head = tk.Frame(self.dock, bg=COLORS['card'])
        head.pack(fill='x', pady=(2, 0))
        ttk.Label(head, text='停靠面板', style='CardMuted.TLabel').pack(side='left',
                                                                       padx=(8, 0))
        collapse = tk.Label(head, text='收起 »', bg=COLORS['card'],
                            fg=COLORS['primary_dark'], font=FONT['bold'],
                            cursor='hand2', padx=8)
        collapse.pack(side='right')
        collapse.bind('<Button-1>', lambda e: self._toggle_dock())
        # 日志操作入口 (原全局 action bar 的"保存/清空日志"迁到这里)
        ttk.Button(head, text='保存日志', style='Tool.TButton',
                   command=self.save_log).pack(side='right', padx=(0, 4))
        ttk.Button(head, text='清空', style='Tool.TButton',
                   command=self.clear_log).pack(side='right', padx=(0, 2))

        self.dock_nb = ttk.Notebook(self.dock)
        self.dock_nb.pack(fill='both', expand=True, padx=4, pady=(2, 4))

        # 页0: 结果 (结构化卡片)
        self.result_panel = ResultPanel(self.dock_nb)
        self.dock_nb.add(self.result_panel, text='结果')

        # 页1: 日志
        log_page = ttk.Frame(self.dock_nb, style='Card.TFrame')
        self.logdock = LogDock(log_page, on_activity=self._on_log_activity)
        self.logdock.pack(fill='both', expand=True)
        self.dock_nb.add(log_page, text='日志')

        # 页2: 详情 (CalibTab 填充; A2L 页签时显示空态)
        self.detail_page = ttk.Frame(self.dock_nb, style='Card.TFrame')
        self.dock_nb.add(self.detail_page, text='详情')
        # 日志委托属性 (页签 _run 里 save_log_file(self.app.log_buffer, ...) 依赖)
        self.log = self.logdock.text
        self.log_buffer = self.logdock.buffer
        self.log_queue = self.logdock.queue
        self.logdock._bar.pack_forget()      # 折叠条迁入 Notebook 后冗余
        self.logdock._sizer.pack_forget()    # 高度随面板, 不再手拖

        self.dock_nb.bind('<<NotebookTabChanged>>', self._on_dock_tab_change)
        self.paned.add(self.center, minsize=460, stretch='always')
        self.paned.add(self.dock, minsize=_DOCK_MIN_W, stretch='never')

    # ---------- 停靠面板: 折叠 / 宽度 / 未读标记 ----------

    def _toggle_dock(self, force_collapsed=None):
        collapsed = force_collapsed if force_collapsed is not None \
            else self.dock.winfo_ismapped() or self.dock.winfo_manager()
        if collapsed:
            try:
                self.paned.forget(self.dock)
            except tk.TclError:
                return
            self.dock_restore_btn.pack(side='right', before=self.status_bar)
        else:
            if self.dock not in self.paned.panes():
                # tk.PanedWindow 无 insert (那是 ttk 的 API); dock 本就是末位面板, add 即可
                self.paned.add(self.dock, minsize=_DOCK_MIN_W,
                               stretch='never',
                               width=max(_DOCK_MIN_W, self.dock.winfo_width()
                                         or _DOCK_DEFAULT_W))
            self.dock_restore_btn.pack_forget()
        appstate.save_app_state(dock_collapsed=1 if collapsed else 0)

    def _apply_dock_width(self, w):
        try:
            self.paned.paneconfigure(self.dock, width=w)
        except tk.TclError:
            pass

    def _save_dock_width(self):
        if self.dock.winfo_ismapped():
            appstate.save_app_state(dock_width=max(_DOCK_MIN_W,
                                                   self.dock.winfo_width()))

    def _on_dock_tab_change(self, event=None):
        try:
            idx = self.dock_nb.index(self.dock_nb.select())
        except tk.TclError:
            return
        appstate.save_app_state(dock_tab=idx)
        # 清掉该页的未读标记
        if idx == 0 and str(self.dock_nb.tab(0, 'text')).endswith('●'):
            self.dock_nb.tab(0, text='结果')
        if idx == 1 and str(self.dock_nb.tab(1, 'text')).endswith('●'):
            self.dock_nb.tab(1, text='日志')

    def select_dock_tab(self, idx):
        """程序化切换停靠面板页签.

        实测 (Py3.9/Tk8.6): select() 不触发 <<NotebookTabChanged>>,
        事件只覆盖用户点击; 程序化切换必须显式跑一次处理器 (幂等)."""
        self.dock_nb.select(idx)
        self._on_dock_tab_change()

    def _on_log_activity(self):
        if self.dock_nb.index(self.dock_nb.select()) != 1:
            self.dock_nb.tab(1, text='日志 ●')

    # ---------- 结果卡片 (阶段2 页签接入) ----------

    def show_result(self, title, metrics=None, paths=None, warns=None, ts=None):
        """推送一张结果卡片到右停靠面板「结果」页; 非当前页时点亮未读标记."""
        self.result_panel.add_result(title, metrics=metrics, paths=paths,
                                     warns=warns, ts=ts)
        if self.dock_nb.index(self.dock_nb.select()) != 0:
            self.dock_nb.tab(0, text='结果 ●')

    # ---------- 导航路由 ----------
    def _on_nav(self, i):
        self.nav_index = i
        if i == 0:
            self.calib_tab.pack_forget()
            self.sub_notebook.pack(fill='both', expand=True)
        else:
            self.sub_notebook.pack_forget()
            self.calib_tab.pack(fill='both', expand=True)
        appstate.save_app_state(last_nav=i)
        self.clear_log()
        self.status('ready', 'A2L处理' if i == 0 else '在线标定')

    def _on_sub_change(self, event=None):
        try:
            sub = self.sub_notebook.index(self.sub_notebook.select())
        except tk.TclError:
            return
        appstate.save_app_state(last_sub=sub)
        # 构建期恢复选中产生的 <<NotebookTabChanged>> 会延迟到首次 update 才触发,
        # 若照常清日志会吞掉启动早期写入的内容 (实测: E2E 探针被清) —— 首次跳过
        if getattr(self, '_nav_ready', False):
            self.clear_log()
        else:
            self._nav_ready = True
        self.status('ready', self.a2l_tabs[sub].TITLE.strip())

    @property
    def active_tab(self):
        if self.nav_index == 0:
            return self.a2l_tabs[self.sub_notebook.index(self.sub_notebook.select())]
        return self.calib_tab

    # ---------- 运行态 / 状态栏 ----------
    def _footer_buttons(self):
        """所有带页脚动作按钮的页签 (A2L 三页签; 在线标定自包含无页脚)."""
        for t in self.a2l_tabs:
            if hasattr(t, 'run_btn'):
                yield t

    def begin_running(self):
        for t in self._footer_buttons():
            t.run_btn.config(state='disabled')
            if hasattr(t, 'test_btn'):
                t.test_btn.config(state='disabled')
        self.progress.pack(side='right', padx=8, pady=2)
        self.progress.start(12)
        self.status('running', '处理中, 请稍候...')

    def end_running(self):
        # 线程结束前先把队列中未渲染的日志刷出, 避免弹窗先于日志显示
        self.logdock.flush()
        self.progress.stop()
        self.progress.pack_forget()
        for t in self._footer_buttons():
            t.run_btn.config(state='normal')
            if hasattr(t, 'test_btn'):
                t.test_btn.config(state='normal')

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
    def log_msg(self, msg, level=None):
        self.logdock.log_msg(msg, level=level)

    def clear_log(self):
        self.logdock.clear()

    def save_log(self):
        self.logdock.save()

    # ---------- 快捷键 ----------
    def _bind_keys(self):
        # F5 运行当前页签; Ctrl+1..3 → A2L处理+对应子Tab; Ctrl+4 → 在线标定
        self.root.bind('<F5>', lambda e: self._f5())
        for i in range(len(self.a2l_tabs)):
            self.root.bind('<Control-Key-%d>' % (i + 1),
                           lambda e, i=i: self._goto(i))
        self.root.bind('<Control-Key-4>', lambda e: self._goto_calib())

    def _f5(self):
        tab = self.active_tab
        if tab is not None and getattr(tab, 'HAS_RUN', False):
            tab.start()

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
