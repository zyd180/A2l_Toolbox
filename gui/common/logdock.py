#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""日志坞: 带着色标签 / 线程安全队列渲染 / 缓冲导出的日志面板."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading

from gui.theme import COLORS, FONT
from utils.logger import pick_log_tag


class LogDock(tk.Frame):
    """日志区组件. 线程安全: 任意线程可调 log_msg/clear/save."""

    def __init__(self, master):
        super().__init__(master, bg=COLORS['border'], padx=1, pady=1)
        self.buffer = []
        self.queue = []             # 工作线程写入, 主线程批量消费
        self._flush_pending = False
        self._open = True
        self._height = 200
        self.pack_propagate(False)
        self.configure(height=self._height)

        self._sizer = tk.Frame(self, height=5, bg=COLORS['border'],
                               cursor='sb_v_double_arrow')
        self._sizer.pack(side='top', fill='x')
        self._sizer.bind('<B1-Motion>', self._resize)

        self._bar = tk.Label(self, text='▾ 日志', bg=COLORS['card'],
                             fg=COLORS['primary_dark'], font=FONT['bold'],
                             anchor='w', padx=8, pady=2, cursor='hand2')
        self._bar.pack(side='top', fill='x')
        self._bar.bind('<Button-1>', lambda e: self.toggle())

        self.text = tk.Text(self, font=FONT['log'], bg=COLORS['log_bg'],
                            fg=COLORS['log_fg'], relief='flat', padx=8, pady=6,
                            insertbackground=COLORS['log_fg'],
                             highlightthickness=0, state='disabled')
        self._scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.text.yview)
        self.text.config(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side='right', fill='y')
        self.text.pack(side='left', fill='both', expand=True)
        for tag, kw in (('err', {'foreground': COLORS['err']}),
                        ('warn', {'foreground': COLORS['warn']}),
                        ('ok', {'foreground': COLORS['ok']}),
                        ('title', {'foreground': COLORS['header'],
                                   'font': FONT['log_b']}),
                        ('dim', {'foreground': COLORS['log_dim']})):
            self.text.tag_configure(tag, **kw)

    def toggle(self):
        """折叠/展开日志体 (收起后仅剩标题条)."""
        self._open = not self._open
        self._bar.configure(text='▾ 日志' if self._open else '▸ 日志')
        if self._open:
            self.pack_propagate(False)
            self.configure(height=self._height)
            self._sizer.pack(side='top', before=self._bar, fill='x')
            self._scrollbar.pack(side='right', fill='y')
            self.text.pack(side='left', fill='both', expand=True)
        else:
            self.text.pack_forget()
            self._scrollbar.pack_forget()
            self._sizer.pack_forget()
            self.pack_propagate(True)

    def _resize(self, event):
        if not self._open:
            return
        bottom = self.winfo_rooty() + self.winfo_height()
        height = max(80, bottom - event.y_root)
        max_height = max(80, self.master.winfo_height() - 100)
        self._height = min(height, max_height)
        self.configure(height=self._height)

    # ---------- 线程判定 ----------
    @staticmethod
    def _on_main():
        return threading.current_thread() is threading.main_thread()

    def _after(self, ms, fn):
        self.after(ms, fn)

    # ---------- 写入 ----------
    def log_msg(self, msg):
        if not self._on_main():
            # 工作线程: 只入队, 由主线程定时批量渲染, 避免逐条调度卡事件队列
            self.queue.append(msg)
            if not self._flush_pending:
                self._flush_pending = True
                self._after(100, self._flush_queue)
            return
        self._insert([msg])

    def _flush_queue(self):
        self._flush_pending = False
        pending, self.queue = self.queue, []
        if not pending:
            return
        self._insert(pending)
        if self.queue:
            self._flush_pending = True
            self._after(100, self._flush_queue)

    def flush(self):
        """弹窗前调用: 立即刷出队列中未渲染日志 (仅主线程)."""
        if self._on_main():
            self._flush_queue()

    def _insert(self, msgs):
        self.text.config(state='normal')
        for msg in msgs:
            tag = pick_log_tag(msg)
            if tag:
                self.text.insert(tk.END, msg + '\n', tag)
            else:
                self.text.insert(tk.END, msg + '\n')
        self.text.see(tk.END)
        self.text.config(state='disabled')
        self.buffer.extend(msgs)

    # ---------- 清空 / 导出 ----------
    def clear(self):
        if not self._on_main():
            self._after(0, self.clear)
            return
        self.queue.clear()
        self.text.config(state='normal')
        self.text.delete(1.0, tk.END)
        self.text.config(state='disabled')
        self.buffer.clear()

    def save(self):
        if not self._on_main():
            self._after(0, self.save)
            return
        self.flush()
        if not self.buffer:
            messagebox.showinfo('提示', '暂无日志')
            return
        path = filedialog.asksaveasfilename(title='保存日志', defaultextension='.txt')
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                for line in self.buffer:
                    f.write(line + '\n')
