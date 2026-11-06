#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""可复用小部件: 文件选择行 / 文件列表(带增删)."""

import tkinter as tk
from tkinter import ttk
from pathlib import Path

from gui.theme import COLORS, FONT


def file_row(parent, row, label, var, cmd, hint=None, col=0):
    """标签 + 输入框 + 浏览按钮 的栅格行; hint 占下一行.

    col=0/1 支持"一行两组"的两列表单 (每组占 4 列: 标签/输入/按钮/间隔),
    默认 col=0 与旧调用完全兼容."""
    base = col * 4
    ttk.Label(parent, text=label, style='Card.TLabel').grid(
        row=row, column=base, sticky='w', padx=(2, 6), pady=3)
    ttk.Entry(parent, textvariable=var).grid(
        row=row, column=base + 1, sticky='ew', padx=(0, 6), pady=3)
    ttk.Button(parent, text='浏览...', command=cmd).grid(
        row=row, column=base + 2, pady=3)
    if hint:
        ttk.Label(parent, text=hint, style='CardMuted.TLabel',
                  wraplength=300, justify='left').grid(
            row=row + 1, column=base, columnspan=3, sticky='w', padx=(0, 6))
    parent.columnconfigure(base + 1, weight=1)


class PathListbox(ttk.Frame):
    """可多选添加/移除/清空的路径列表 (更新A2L 的模型列表)."""

    def __init__(self, master, height=4):
        super().__init__(master, style='Card.TFrame')
        self.listbox = tk.Listbox(
            self, height=height, selectmode='extended', relief='flat',
            bg=COLORS['card'], fg=COLORS['text'], highlightthickness=1,
            highlightbackground=COLORS['border'], highlightcolor=COLORS['primary'],
            selectbackground=COLORS['primary'], selectforeground='white',
            font=FONT['body'])
        self.listbox.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(self, orient='vertical', command=self.listbox.yview)
        sb.pack(side='right', fill='y')
        self.listbox.config(yscrollcommand=sb.set)

    def add_paths(self, paths):
        existing = set(self.get_all())
        for p in paths:
            if p not in existing:
                self.listbox.insert(tk.END, p)
                existing.add(p)

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)

    def clear(self):
        self.listbox.delete(0, tk.END)

    def get_all(self):
        return list(self.listbox.get(0, tk.END))
