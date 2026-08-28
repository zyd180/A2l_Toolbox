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
<<<<<<< HEAD
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


    # ---------- 样式 ----------
    def _setup_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        base_font = ("微软雅黑", 9)
        style.configure('.', font=base_font, background=COLORS['bg'], foreground=COLORS['text'])
        style.configure('TFrame', background=COLORS['bg'])
        style.configure('Card.TFrame', background=COLORS['card'])
        style.configure('TLabel', background=COLORS['bg'])
        style.configure('Card.TLabel', background=COLORS['card'])
        style.configure('CardMuted.TLabel', background=COLORS['card'], foreground=COLORS['muted'])
        style.configure('TButton', padding=(10, 5))
        style.configure('Primary.TButton', background=COLORS['primary'], foreground='white',
                        borderwidth=0, focusthickness=0, padding=(20, 7),
                        font=("微软雅黑", 9, "bold"))
        style.map('Primary.TButton',
                  background=[('active', COLORS['primary_dark']), ('disabled', '#9db8e8')],
                  foreground=[('disabled', '#eaf1fb')])
        style.configure('TEntry', padding=4, fieldbackground=COLORS['card'], bordercolor=COLORS['border'])
        style.configure('Card.TRadiobutton', background=COLORS['card'])
        style.configure('Card.TCheckbutton', background=COLORS['card'])
        style.map('Card.TRadiobutton', background=[('active', COLORS['card'])])
        style.map('Card.TCheckbutton', background=[('active', COLORS['card'])])
        style.configure('Card.TLabelframe', background=COLORS['card'], bordercolor=COLORS['border'],
                        relief='solid', borderwidth=1)
        style.configure('Card.TLabelframe.Label', background=COLORS['card'],
                        foreground=COLORS['primary_dark'], font=("微软雅黑", 9, "bold"))
        style.configure('TNotebook', background=COLORS['card'], borderwidth=0)
        style.configure('TNotebook.Tab', padding=(18, 7), background='#dbe3ee',
                        font=("微软雅黑", 9))
        style.map('TNotebook.Tab',
                  background=[('selected', COLORS['card'])],
                  foreground=[('selected', COLORS['primary_dark'])],
                  font=[('selected', ("微软雅黑", 9, "bold"))],
                  expand=[('selected', (0, 0, 0, 2))])
        style.configure('Accent.Horizontal.TProgressbar', troughcolor='#dbe3ee',
                        background=COLORS['primary'], borderwidth=0, thickness=6)

    # ---------- 界面 ----------
    def build_ui(self):
        main = tk.Frame(self.root, bg=COLORS['bg'])
        main.pack(fill="both", expand=True)

        # === 顶部横幅 ===
        header = tk.Frame(main, bg=COLORS['header'])
        header.pack(fill="x")
        inner = tk.Frame(header, bg=COLORS['header'])
        inner.pack(fill="x", padx=16, pady=10)
        tk.Label(inner, text="A2L 工具箱", bg=COLORS['header'], fg='white',
                 font=("微软雅黑", 16, "bold")).pack(side="left")
        tk.Label(inner, text=VERSION, bg=COLORS['header'], fg=COLORS['header_sub'],
                 font=("微软雅黑", 9)).pack(side="left", padx=(8, 0), pady=(8, 0))
        link = tk.Label(inner, text="GitHub: https://github.com/zyd180", bg=COLORS['header'],
                        fg='#8ab4f8', cursor="hand2", font=("微软雅黑", 9))
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/zyd180"))
        tk.Label(inner, text="开发者: Henry", bg=COLORS['header'], fg=COLORS['header_sub'],
                 font=("微软雅黑", 9)).pack(side="right", padx=(0, 14))

        # === 底部状态栏 (先打包固定底部) ===
        self.status = tk.StringVar(value="  就绪")
        self.status_bar = tk.Label(main, textvariable=self.status, anchor="w", bg=COLORS['ready_bg'],
                                   fg='#374151', font=("微软雅黑", 9), padx=8, pady=3)
        self.status_bar.pack(side="bottom", fill="x")

        body = tk.Frame(main, bg=COLORS['bg'])
        body.pack(fill="both", expand=True, padx=12, pady=(8, 8))

        # === 功能页签 ===
        self.notebook = ttk.Notebook(body)
        self.notebook.pack(fill="x")
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_change)

        # === 地址映射面板 ===
        self.update_frame = ttk.Frame(self.notebook, style='Card.TFrame', padding=12)
        self.notebook.add(self.update_frame, text="  地址映射  ")

        ttk.Label(self.update_frame,
                  text="根据 ELF/MAP 文件中的符号地址, 更新 A2L 中变量的 ECU 地址 (可选删除未匹配变量)",
                  style='CardMuted.TLabel').pack(anchor="w", pady=(0, 8))

        grp_src = ttk.Labelframe(self.update_frame, text=" 符号源 ", style='Card.TLabelframe', padding=10)
        grp_src.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(grp_src, text="ELF 文件", variable=self.source_type, value="elf",
                        style='Card.TRadiobutton').grid(row=0, column=1, sticky="w", padx=(0, 24), pady=(0, 4))
        ttk.Radiobutton(grp_src, text="MAP 文件", variable=self.source_type, value="map",
                        style='Card.TRadiobutton').grid(row=0, column=2, sticky="w", pady=(0, 4))
        self.src_var = tk.StringVar()
        self._file_row(grp_src, 1, "源文件:", self.src_var, self.browse_src)

        grp_io = ttk.Labelframe(self.update_frame, text=" A2L 文件 ", style='Card.TLabelframe', padding=10)
        grp_io.pack(fill="x", pady=(0, 8))
        self.a2l_in_var = tk.StringVar()
        self.a2l_out_var = tk.StringVar()
        self._file_row(grp_io, 0, "A2L输入:", self.a2l_in_var, self.browse_a2l_in)
        self._file_row(grp_io, 1, "A2L输出:", self.a2l_out_var, self.browse_a2l_out)

        opt = ttk.Frame(self.update_frame, style='Card.TFrame')
        opt.pack(fill="x")
        ttk.Checkbutton(opt, text="删除A2L中有但ELF/MAP中没有的变量", variable=self.remove_var,
                        style='Card.TCheckbutton').pack(side="left", padx=4)

        # === 合并A2L面板 ===
        self.merge_frame = ttk.Frame(self.notebook, style='Card.TFrame', padding=12)
        self.notebook.add(self.merge_frame, text="  合并A2L  ")

        ttk.Label(self.merge_frame,
                  text="将文件夹中的多个 A2L 文件合并为一个: 可指定头文件 A2L 插入 Data 标记处, 或输出去壳纯内容",
                  style='CardMuted.TLabel').pack(anchor="w", pady=(0, 8))

        grp_m = ttk.Labelframe(self.merge_frame, text=" 文件选择 ", style='Card.TLabelframe', padding=10)
        grp_m.pack(fill="x", pady=(0, 8))
        self.merge_folder_var = tk.StringVar()
        self.merge_output_var = tk.StringVar()
        self.merge_header_var = tk.StringVar()
        self._file_row(grp_m, 0, "输入文件夹:", self.merge_folder_var, self.browse_merge_folder)
        self._file_row(grp_m, 1, "输出文件:", self.merge_output_var, self.browse_merge_output)
        self._file_row(grp_m, 2, "头文件A2L:", self.merge_header_var, self.browse_merge_header,
                       hint="(可选) 选择后将合并内容插入此文件的 Data 区域")

        mopt = ttk.Frame(self.merge_frame, style='Card.TFrame')
        mopt.pack(fill="x")
        ttk.Checkbutton(mopt, text="包含子文件夹", variable=self.recursive_var,
                        style='Card.TCheckbutton').pack(side="left", padx=4)

        # === 更新A2L面板 ===
        self.sync_frame = ttk.Frame(self.notebook, style='Card.TFrame', padding=12)
        self.notebook.add(self.sync_frame, text="  更新A2L  ")

        ttk.Label(self.sync_frame,
                  text="将一个或多个新版模型 A2L 中的变量/标定量/曲线/MAP 更新进整车 A2L (保留已有 ECU 地址, GROUP 不同步不保留)",
                  style='CardMuted.TLabel').pack(anchor="w", pady=(0, 8))

        grp_sync = ttk.Labelframe(self.sync_frame, text=" 文件选择 ", style='Card.TLabelframe', padding=10)
        grp_sync.pack(fill="x", pady=(0, 8))

        ttk.Label(grp_sync, text="新模型A2L:", style='Card.TLabel').grid(row=0, column=0, sticky="nw", padx=(2, 6), pady=3)
        src_box = ttk.Frame(grp_sync, style='Card.TFrame')
        src_box.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=3)
        self.sync_src_listbox = tk.Listbox(src_box, height=4, selectmode="extended",
                                           relief="flat", bg=COLORS['card'], fg=COLORS['text'],
                                           highlightthickness=1, highlightbackground=COLORS['border'],
                                           highlightcolor=COLORS['primary'],
                                           selectbackground=COLORS['primary'], selectforeground='white',
                                           font=("微软雅黑", 9))
        self.sync_src_listbox.pack(side="left", fill="both", expand=True)
        src_sb = ttk.Scrollbar(src_box, orient="vertical", command=self.sync_src_listbox.yview)
        src_sb.pack(side="right", fill="y")
        self.sync_src_listbox.config(yscrollcommand=src_sb.set)
        src_btns = ttk.Frame(grp_sync, style='Card.TFrame')
        src_btns.grid(row=0, column=2, sticky="n")
        ttk.Button(src_btns, text="添加...", command=self.browse_sync_src).pack(fill="x", pady=(0, 3))
        ttk.Button(src_btns, text="移除", command=self.remove_sync_src).pack(fill="x", pady=(0, 3))
        ttk.Button(src_btns, text="清空", command=self.clear_sync_src).pack(fill="x")

        self.sync_tgt_var = tk.StringVar()
        self.sync_out_var = tk.StringVar()
        self._file_row(grp_sync, 1, "Base A2L:", self.sync_tgt_var, self.browse_sync_tgt)
        self._file_row(grp_sync, 2, "A2L输出:", self.sync_out_var, self.browse_sync_out,
                       hint="默认覆盖整车 A2L (启用备份时先生成 .bak)")
        grp_sync.columnconfigure(1, weight=1)

        sopt = ttk.Frame(self.sync_frame, style='Card.TFrame')
        sopt.pack(fill="x")
        self.sync_purge_var = tk.BooleanVar(value=True)
        self.sync_backup_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(sopt, text="删除旧版有而新版没有的对象 (完全以新版为准)",
                        variable=self.sync_purge_var, style='Card.TCheckbutton').pack(side="left", padx=(4, 24))
        ttk.Checkbutton(sopt, text="备份目标文件 (.bak)",
                        variable=self.sync_backup_var, style='Card.TCheckbutton').pack(side="left")

        # 内嵌可选步骤: 同步完成后对输出 A2L 整体刷新地址
        self.sync_addr_var = tk.BooleanVar(value=False)
        self.sync_sym_var = tk.StringVar()
        ttk.Checkbutton(sopt, text="同步完成后自动更新地址 (ELF/MAP → 输出 A2L)",
                        variable=self.sync_addr_var, style='Card.TCheckbutton',
                        command=self._toggle_sync_addr).pack(side="left", padx=(24, 0))
        self.sync_addr_row = ttk.Frame(self.sync_frame, style='Card.TFrame')
        self._file_row(self.sync_addr_row, 0, "地址文件:",
                       self.sync_sym_var, self.browse_sync_sym,
                       hint="按扩展名自动识别 ELF/MAP; 对同步输出整体执行地址更新")

        # === 在线标定面板 (自包含页签, 对标 INCA) ===
        self.calib_frame = ttk.Frame(self.notebook, style='Card.TFrame')
        self.notebook.add(self.calib_frame, text="  在线标定  ")
        self.calib_tab = CalibTab(self.calib_frame, app=self)
        self.calib_tab.pack(fill="both", expand=True)

        # === 操作按钮区 ===
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(10, 4))
        self.run_btn = ttk.Button(bar, text="开始", style="Primary.TButton", command=self.start_processing)
        self.run_btn.pack(side="left")
        self.test_btn = ttk.Button(bar, text="测试解析", command=self.test_parse)
        self.test_btn.pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="保存日志", command=self.save_log).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="清空日志", command=self.clear_log).pack(side="right")

        # === 进度条 (运行时显示) ===
        self.progress = ttk.Progressbar(body, mode="indeterminate",
                                        style='Accent.Horizontal.TProgressbar')

        # === 日志区 ===
        log_wrap = tk.Frame(body, bg=COLORS['border'], padx=1, pady=1)
        self.log_wrap = log_wrap
        log_wrap.pack(fill="both", expand=True, pady=(4, 0))
        self.log = tk.Text(log_wrap, font=("Consolas", 9), bg='#fbfcfe', fg='#24313f',
                           relief="flat", padx=8, pady=6, insertbackground='#24313f',
                           highlightthickness=0, state="disabled")
        log_sb = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview)
        self.log.config(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure('err', foreground=COLORS['err'])
        self.log.tag_configure('warn', foreground=COLORS['warn'])
        self.log.tag_configure('ok', foreground=COLORS['ok'])
        self.log.tag_configure('title', foreground=COLORS['header'], font=("Consolas", 9, "bold"))
        self.log.tag_configure('dim', foreground='#8a94a3')

    def _file_row(self, parent, row, label, var, cmd, hint=None):
        """通用文件选择行: 标签 + 输入框 + 浏览按钮"""
        ttk.Label(parent, text=label, style='Card.TLabel').grid(row=row, column=0, sticky="w", padx=(2, 6), pady=3)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=3)
        ttk.Button(parent, text="浏览...", command=cmd).grid(row=row, column=2, pady=3)
        if hint:
            ttk.Label(parent, text=hint, style='CardMuted.TLabel').grid(row=row + 1, column=1, sticky="w", padx=(0, 6))
        parent.columnconfigure(1, weight=1)
    
    def on_tab_change(self, event=None):
        tab_id = self.notebook.index(self.notebook.select())
        if tab_id == 3:  # 在线标定: 自包含页签, 隐藏全局按钮
            self.test_btn.pack_forget()
            self.run_btn.pack_forget()
        else:
            self.run_btn.pack(side="left")
            if tab_id == 0:  # 地址映射
                self.test_btn.pack(side="left", padx=5)
                self.run_btn.config(text="开始更新")
            elif tab_id == 1:  # 合并A2L
                self.test_btn.pack_forget()
                self.run_btn.config(text="开始合并")
            else:  # 更新A2L
                self.test_btn.pack_forget()
                self.run_btn.config(text="开始同步")
        self.clear_log()
    
    # ---------- 运行态 / 状态栏 ----------
    def _begin_running(self):
        self.run_btn.config(state="disabled")
        self.test_btn.config(state="disabled")
        self.progress.pack(fill="x", pady=(0, 4), before=self.log_wrap)
        self.progress.start(12)
        self._status("running", "处理中, 请稍候...")

    def _end_running(self):
        # 线程结束前先把队列中未渲染的日志刷出, 避免弹窗先于日志显示
        self._flush_log_queue()
        self.progress.stop()
        self.progress.pack_forget()
        self.run_btn.config(state="normal")
        self.test_btn.config(state="normal")

    def _status(self, level, text):
        """更新状态栏 (带颜色): ready/running/ok/err"""
        colors = {
            'ready':   (COLORS['ready_bg'], '#374151'),
            'running': (COLORS['run_bg'],   COLORS['primary_dark']),
            'ok':      (COLORS['ok_bg'],    COLORS['ok']),
            'err':     (COLORS['err_bg'],   COLORS['err']),
        }
        bg, fg = colors.get(level, colors['ready'])
        self.status.set("  " + text)
        self.status_bar.config(bg=bg, fg=fg)

    # ---------- 线程安全的 UI 操作 ----------
    def _on_main(self):
        return threading.current_thread() is threading.main_thread()

    def log_msg(self, msg):
        if not self._on_main():
            # 工作线程: 只入队, 由主线程定时批量渲染,
            # 避免每条日志都调度一次 after + 强制滚动, 卡顺事件队列/进度条动画
            self._log_queue.append(msg)
            if not self._log_flush_pending:
                self._log_flush_pending = True
                self.root.after(100, self._flush_log_queue)
            return
        self._insert_log_lines([msg])

    def _flush_log_queue(self):
        self._log_flush_pending = False
        pending, self._log_queue = self._log_queue, []
        if not pending:
            return
        self._insert_log_lines(pending)
        if self._log_queue:
            self._log_flush_pending = True
            self.root.after(100, self._flush_log_queue)

    def _insert_log_lines(self, msgs):
        self.log.config(state="normal")
        for msg in msgs:
            tag = pick_log_tag(msg)
            if tag:
                self.log.insert(tk.END, msg + "\n", tag)
            else:
                self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")
        self.log_buffer.extend(msgs)

    def clear_log(self):
        if not self._on_main():
            self.root.after(0, self.clear_log)
            return
        self._log_queue.clear()
        self.log.config(state="normal")
        self.log.delete(1.0, tk.END)
        self.log.config(state="disabled")
        self.log_buffer.clear()

    def _info(self, title, msg):
        if not self._on_main():
            self.root.after(0, self._info, title, msg)
            return
        self._flush_log_queue()
        messagebox.showinfo(title, msg)

    def _error(self, title, msg):
        if not self._on_main():
            self.root.after(0, self._error, title, msg)
            return
        self._flush_log_queue()
        messagebox.showerror(title, msg)
    
    def save_log(self):
        if not self._on_main():
            self.root.after(0, self.save_log)
            return
        self._flush_log_queue()
        if not self.log_buffer:
            messagebox.showinfo("提示", "暂无日志")
            return
        path = filedialog.asksaveasfilename(title="保存日志", defaultextension=".txt")
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                for line in self.log_buffer:
                    f.write(line + "\n")
    
    def browse_src(self):
        ft = FILE_TYPES['elf'] if self.source_type.get() == "elf" else FILE_TYPES['map']
        p = filedialog.askopenfilename(title="选择源文件", filetypes=ft + FILE_TYPES['all'])
        if p: self.src_var.set(p)
    
    def browse_a2l_in(self):
        p = filedialog.askopenfilename(title="选择A2L文件", filetypes=FILE_TYPES['a2l'])
        if p:
            self.a2l_in_var.set(p)
            if not self.a2l_out_var.get():
                pp = Path(p)
                self.a2l_out_var.set(str(pp.parent / f"{pp.stem}_updated{pp.suffix}"))
    
    def browse_a2l_out(self):
        p = filedialog.asksaveasfilename(title="保存A2L", defaultextension=".a2l")
        if p: self.a2l_out_var.set(p)
    
    def browse_merge_folder(self):
        p = filedialog.askdirectory(title="选择包含A2L文件的文件夹")
        if p:
            self.merge_folder_var.set(p)
            if not self.merge_output_var.get():
                self.merge_output_var.set(str(Path(p) / "merged.a2l"))
    
    def browse_merge_output(self):
        p = filedialog.asksaveasfilename(title="保存合并后的A2L", defaultextension=".a2l")
        if p: self.merge_output_var.set(p)
    
    def browse_merge_header(self):
        p = filedialog.askopenfilename(title="选择头文件A2L", filetypes=FILE_TYPES['a2l'])
        if p: self.merge_header_var.set(p)
    
    def browse_sync_src(self):
        paths = filedialog.askopenfilenames(title="选择新版模型 A2L (可多选)", filetypes=FILE_TYPES['a2l'])
        if paths:
            existing = set(self.sync_src_listbox.get(0, tk.END))
            for p in paths:
                if p not in existing:
                    self.sync_src_listbox.insert(tk.END, p)
                    existing.add(p)
    
    def remove_sync_src(self):
        for i in reversed(self.sync_src_listbox.curselection()):
            self.sync_src_listbox.delete(i)
    
    def clear_sync_src(self):
        self.sync_src_listbox.delete(0, tk.END)
    
    def browse_sync_tgt(self):
        p = filedialog.askopenfilename(title="选择整车 A2L", filetypes=FILE_TYPES['a2l'])
        if p:
            self.sync_tgt_var.set(p)
            if not self.sync_out_var.get():
                self.sync_out_var.set(p)
    
    def browse_sync_out(self):
        p = filedialog.asksaveasfilename(title="保存输出 A2L", defaultextension=".a2l")
        if p: self.sync_out_var.set(p)

    def browse_sync_sym(self):
        p = filedialog.askopenfilename(title="选择 ELF/MAP 地址文件",
                                       filetypes=FILE_TYPES['elf'] + FILE_TYPES['map'])
        if p: self.sync_sym_var.set(p)

    def _toggle_sync_addr(self):
        if self.sync_addr_var.get():
            self.sync_addr_row.pack(fill='x', pady=(4, 0))
        else:
            self.sync_addr_row.pack_forget()
    
    def test_parse(self):
        src = self.src_var.get().strip()
        a2l = self.a2l_in_var.get().strip()
        if not src or not a2l:
            messagebox.showerror("错误", "请先选择文件")
            return
        self.clear_log()
        self.log_msg("=== 测试解析 ===\n")
        stype = self.source_type.get()
        try:
            self.symbols = parse_elf_symbols(src) if stype == "elf" else parse_map_symbols(src)
            self.log_msg(f"[{stype.upper()}] 符号数: {len(self.symbols)}")
            for n, a in list(self.symbols.items())[:10]:
                self.log_msg(f"  {n:40s} 0x{a:08X}")
        except Exception as e:
            self.log_msg(f"解析失败: {e}")
            return
        
        self.log_msg("\n[A2L] 解析变量...")
        try:
            variables, _ = extract_a2l_variables(a2l)
            self.log_msg(f"变量数: {len(variables)}")
            for v in variables[:5]:
                self.log_msg(f"  {v['name']:40s} 行{v['addr_line']}")
        except Exception as e:
            self.log_msg(f"解析失败: {e}")
    
    def start_processing(self):
        tab_id = self.notebook.index(self.notebook.select())
        if tab_id == 0:
            self.start_update()
        elif tab_id == 1:
            self.start_merge()
        elif tab_id == 2:
            self.start_sync()
    
    def start_update(self):
        src = self.src_var.get().strip()
        a2l_in = self.a2l_in_var.get().strip()
        a2l_out = self.a2l_out_var.get().strip()
        
        if not all([src, a2l_in, a2l_out]):
            messagebox.showerror("错误", "请填写所有路径")
            return
        if not Path(src).exists() or not Path(a2l_in).exists():
            messagebox.showerror("错误", "源文件或A2L输入不存在")
            return
        
        self._begin_running()
        t = threading.Thread(target=self._do_update, args=(src, a2l_in, a2l_out, self.remove_var.get()), daemon=True)
        t.start()
    
    def _do_update(self, src, a2l_in, a2l_out, remove_unmatched=False):
        import time
        start = time.time()
        try:
            self.clear_log()
            stype = self.source_type.get()
            
            self.log_msg("=" * 60)
            self.log_msg("地址映射 - 处理日志")
            self.log_msg("=" * 60)
            self.log_msg(f"时间: {timestamp()}")
            self.log_msg(f"源类型: {stype.upper()} | 源文件: {src}")
            self.log_msg(f"A2L输入: {a2l_in}")
            self.log_msg(f"A2L输出: {a2l_out}")
            self.log_msg(f"删除未匹配: {'是' if remove_unmatched else '否'}")
            self.log_msg("=" * 60)
            
            # 1. 解析
            self.log_msg("\n[1/3] 解析源文件...")
            self.symbols = parse_elf_symbols(src) if stype == "elf" else parse_map_symbols(src)
            self.log_msg(f"  符号数: {len(self.symbols)}")
            
            # 2. 更新
            self.log_msg("\n[2/3] 映射地址...")
            total, matched, updated, _, stats = update_a2l_file(a2l_in, self.symbols, a2l_out, remove_unmatched)
            
            self.log_msg("\n[3/3] 保存完成")
            
            # 统计
            elapsed = time.time() - start
            rate = f"{matched/total*100:.1f}%" if total > 0 else "0%"
            self.log_msg(f"\n{'='*60}")
            self.log_msg("统计汇总")
            self.log_msg(f"{'='*60}")
            self.log_msg(f"  变量总数: {total}")
            self.log_msg(f"  匹配符号: {matched} ({rate})")
            self.log_msg(f"  地址更新: {updated}")
            self.log_msg(f"  地址未变: {stats['unchanged']}")
            self.log_msg(f"  未匹配:   {stats['unmatched']}")
            self.log_msg(f"  已删除:   {stats['removed_count']}")
            self.log_msg(f"  ELF独有:  {len(stats['elf_only_vars'])}")
            self.log_msg(f"  处理耗时: {elapsed:.2f}s")
            self.log_msg(f"{'='*60}")
            
            # 自动保存日志
            log_path = save_log_file(self.log_buffer, self._log_queue, a2l_out)
            if log_path:
                self.log_msg(f"\n日志已保存: {log_path}")
            
            self.root.after(0, self._status, "ok", f"完成! 更新 {updated}/{matched}")
            msg = f"更新完成!\n\n变量总数: {total}\n匹配: {matched}({rate})\n更新: {updated}\n未变: {stats['unchanged']}\n未匹配: {stats['unmatched']}\n已删除: {stats['removed_count']}\n耗时: {elapsed:.2f}s"
            if log_path: msg += f"\n\n日志: {log_path}"
            self._info("完成", msg)
        
        except Exception as e:
            self.log_msg(f"错误: {e}\n{traceback.format_exc()}")
            self.root.after(0, self._status, "err", f"出错: {e}")
            self._error("错误", str(e))
        finally:
            self.root.after(0, self._end_running)
    
    def start_merge(self):
        folder = self.merge_folder_var.get().strip()
        output = self.merge_output_var.get().strip()
        header = self.merge_header_var.get().strip()
        if not folder or not output:
            messagebox.showerror("错误", "请填写输入文件夹和输出文件")
            return
        if not Path(folder).exists():
            messagebox.showerror("错误", "文件夹不存在")
            return
        if header and not Path(header).exists():
            messagebox.showerror("错误", "头文件A2L不存在")
            return
        
        self._begin_running()
        t = threading.Thread(target=self._do_merge, args=(folder, output, header, self.recursive_var.get()), daemon=True)
        t.start()
    
    def _do_merge(self, folder, output, header, recursive):
        import time
        start = time.time()
        try:
            self.clear_log()
            self.log_msg("=" * 60)
            self.log_msg("合并 A2L - 处理日志")
            self.log_msg("=" * 60)
            self.log_msg(f"时间: {timestamp()}")
            self.log_msg(f"输入文件夹: {folder}")
            self.log_msg(f"输出文件: {output}")
            self.log_msg(f"头文件A2L: {header if header else '(无, 输出纯内容)'}")
            self.log_msg(f"包含子文件夹: {'是' if recursive else '否'}")
            self.log_msg("=" * 60)
            
            self.log_msg("\n[1/3] 扫描并提取 A2L 内容...")
            record_lines, variable_blocks, compu_lines, file_var_map, file_count = extract_a2l_content(folder, recursive)
            
            total_vars = len(variable_blocks)
            self.log_msg(f"  文件数: {file_count}")
            self.log_msg(f"  变量块: {total_vars}")
            self.log_msg(f"  RECORD_LAYOUT: {len(record_lines)}")
            self.log_msg(f"  COMPU_METHOD: {len(compu_lines)}")
            self.log_msg(f"  有变量的文件: {len([k for k,v in file_var_map.items() if any(v[x] for x in v)])}")
            
            self.log_msg("\n[2/3] 写入内容...")
            
            if header:
                # 有头文件 - 插入到 Data 区域
                insert_into_header(header, record_lines, variable_blocks, compu_lines, file_var_map, output)
                self.log_msg("  模式: 插入了文件")
            else:
                # 无头文件 - 输出纯内容
                write_content_only(record_lines, variable_blocks, compu_lines, file_var_map, output)
                self.log_msg("  模式: 纯内容输出 (去壳)")
            
            elapsed = time.time() - start
            
            self.log_msg(f"\n[3/3] 完成")
            self.log_msg(f"\n{'='*60}")
            self.log_msg("合并统计")
            self.log_msg(f"{'='*60}")
            self.log_msg(f"  源文件数:     {file_count}")
            self.log_msg(f"  变量块总数:   {total_vars}")
            self.log_msg(f"  RECORD_LAYOUT: {len(record_lines)}")
            self.log_msg(f"  COMPU_METHOD:  {len(compu_lines)}")
            self.log_msg(f"  处理耗时:     {elapsed:.2f}s")
            self.log_msg(f"{'='*60}")
            
            mode_str = "插入头文件" if header else "纯内容"
            self.root.after(0, self._status, "ok", f"完成! {file_count}文件, {total_vars}变量 [{mode_str}]")
            self._info("完成", f"合并完成!\n\n源文件: {file_count}\n变量块: {total_vars}\n模式: {mode_str}\n耗时: {elapsed:.2f}s\n\n输出: {output}")
        
        except Exception as e:
            self.log_msg(f"错误: {e}\n{traceback.format_exc()}")
            self.root.after(0, self._status, "err", f"出错: {e}")
            self._error("错误", str(e))
        finally:
            self.root.after(0, self._end_running)
    
    def start_sync(self):
        sources = list(self.sync_src_listbox.get(0, tk.END))
        tgt = self.sync_tgt_var.get().strip()
        out = self.sync_out_var.get().strip()
        if not sources or not tgt or not out:
            messagebox.showerror("错误", "请添加新模型 A2L 并填写 Base A2L 与输出路径")
            return
        for s in sources:
            if not Path(s).exists():
                messagebox.showerror("错误", f"新模型 A2L 不存在:\n{s}")
                return
        if not Path(tgt).exists():
            messagebox.showerror("错误", "整车 A2L 不存在")
            return
        backup = self.sync_backup_var.get()
        purge = self.sync_purge_var.get()
        sym = self.sync_sym_var.get().strip() if self.sync_addr_var.get() else ''
        if self.sync_addr_var.get():
            if not sym:
                messagebox.showerror("错误", "已勾选自动更新地址, 请选择地址文件 (ELF/MAP)")
                return
            if not Path(sym).exists():
                messagebox.showerror("错误", f"地址文件不存在: {sym}")
                return
        if Path(out).resolve() == Path(tgt).resolve() and not backup:
            if not messagebox.askyesno("确认", "输出将覆盖整车 A2L 且未勾选备份, 是否继续?"):
                return

        self._begin_running()
        t = threading.Thread(target=self._do_sync,
                             args=(sources, tgt, out, purge, backup, sym), daemon=True)
        t.start()

    def _do_sync(self, sources, tgt, out, purge, backup, sym=''):
        import time
        start = time.time()
        try:
            self.clear_log()
            self.log_msg("=" * 60)
            self.log_msg("更新A2L - 处理日志")
            self.log_msg("=" * 60)
            self.log_msg(f"时间: {timestamp()}")
            self.log_msg(f"新模型 A2L ({len(sources)} 个):")
            for s in sources:
                self.log_msg(f"  - {s}")
            self.log_msg(f"Base A2L:  {tgt}")
            self.log_msg(f"A2L 输出:  {out}")
            self.log_msg(f"删除旧版遗留对象: {'是' if purge else '否'}")
            self.log_msg(f"备份目标文件:       {'是' if backup else '否'}")
            if sym:
                self.log_msg(f"完成后自动更新地址: {sym}")
            self.log_msg("=" * 60)
            
            # 依次同步: 第一个模型以 Base A2L 为基准, 后续模型基于上次输出继续
            all_stats = []
            cur_tgt = tgt
            for i, src in enumerate(sources):
                self.log_msg(f"\n>>> [{i+1}/{len(sources)}] 同步模型: {Path(src).name}")
                stats = sync_model_a2l(src, cur_tgt, out, purge=purge,
                                       backup=(backup and i == 0), log=self.log_msg)
                all_stats.append((Path(src).name, stats))
                cur_tgt = out
            
            elapsed = time.time() - start
            self.log_msg(f"\n{'='*60}")
            self.log_msg("同步统计")
            self.log_msg(f"{'='*60}")
            tot_r = tot_a = tot_d = tot_s = tot_w = 0
            for name, stats in all_stats:
                line = (f"  {name}: 对象 {stats['src_total']}, 替换/更新 {stats['replaced']}, "
                        f"新增 {stats['added']}")
                if purge:
                    line += f", 删除 {stats['deleted']}"
                fstats = stats.get('function', {})
                if fstats.get('changed'):
                    line += f", FUNCTION{'新增' if fstats.get('added') else '重建'}: {fstats.get('name')}"
                self.log_msg(line)
                tot_r += stats['replaced']
                tot_a += stats['added']
                tot_d += stats['deleted']
                tot_s += len(stats['kept_same'])
                tot_w += len(stats['kept_warn'])
            self.log_msg("-" * 60)
            self.log_msg(f"  合计: 替换/更新 {tot_r}, 新增 {tot_a}, 删除 {tot_d}, 保持未变 {tot_s}")
            if purge:
                self.log_msg(f"  引用保留警告: {tot_w}")
            self.log_msg(f"  处理耗时:     {elapsed:.2f}s")
            self.log_msg(f"{'='*60}")

            # ---- 内嵌可选步骤: 对输出 A2L 整体刷新地址 ----
            addr_info = ''
            if sym:
                self.log_msg("")
                self.log_msg(">>> 自动更新地址: %s" % Path(sym).name)
                try:
                    stype = 'map' if sym.lower().endswith('.map') else 'elf'
                    symbols = (parse_map_symbols(sym) if stype == 'map'
                               else parse_elf_symbols(sym))
                    self.log_msg("  地址文件类型: %s, 符号数: %d"
                                 % (stype.upper(), len(symbols)))
                    total, matched, updated, _x, astats = update_a2l_file(
                        out, symbols, out)
                    un = astats.get('unmatched', 0)
                    self.log_msg("  变量 %d | 匹配 %d | 地址更新 %d | 未匹配 %d"
                                 % (total, matched, updated, un))
                    addr_info = (f"\n地址更新: {updated}/{matched} (未匹配 {un})")
                except Exception as ae:
                    self.log_msg(f"  地址更新失败: {ae}")
                    addr_info = "\n地址更新: 失败 (%s)" % ae

            log_path = save_log_file(self.log_buffer, self._log_queue, out)
            if log_path:
                self.log_msg(f"\n日志已保存: {log_path}")
            
            self.root.after(0, self._status, "ok", f"完成! {len(sources)} 个模型: 更新 {tot_r}, 新增 {tot_a}, 删除 {tot_d}")
            purge_str = f"删除旧版遗留: {tot_d}\n" if purge else ""
            msg = (f"同步完成!\n\n模型数: {len(sources)}\n替换/更新: {tot_r}\n新增: {tot_a}\n"
                   f"{purge_str}保持未变: {tot_s}{addr_info}\n耗时: {elapsed:.2f}s\n\n输出: {out}")
            if tot_w:
                msg += f"\n\n注意: {tot_w} 个对象因块外仍有引用而未删除, 详见日志!"
            if log_path: msg += f"\n\n日志: {log_path}"
            self._info("完成", msg)
        
        except Exception as e:
            self.log_msg(f"错误: {e}\n{traceback.format_exc()}")
            self.root.after(0, self._status, "err", f"出错: {e}")
            self._error("错误", str(e))
        finally:
            self.root.after(0, self._end_running)
    
>>>>>>> 7ee5f86224b367e6130a31c33f3c6ff99628b94f
