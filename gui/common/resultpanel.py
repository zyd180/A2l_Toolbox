#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""结果面板: 右停靠面板的「结果」页 — 结构化结果卡片, 常驻可回看.

替代旧版"跑完弹一个 messagebox"的反馈方式: 成功结果写卡片常驻
(统计指标/产物路径/警告清单), messagebox 只保留错误与需要确认的场景。

API:
    panel.add_result(title, metrics=[(k, v)...], paths=[...], warns=[...], ts=None)
    panel.clear()
卡片数量上限 _MAX_CARDS, 超出丢弃最旧的 (防长会话内存膨胀)。
"""

import tkinter as tk
from tkinter import ttk

from gui.theme import COLORS, FONT, DIVIDER

_MAX_CARDS = 20


class ResultPanel(ttk.Frame):
    """纵向滚动卡片列表; 空态显示提示文字。"""

    def __init__(self, master):
        super().__init__(master, style='Card.TFrame')
        self.cards = []          # [{title, metrics, paths, warns, ts}]
        self._body = None        # 当前卡片容器 (重渲染时整体重建)

        self.canvas = tk.Canvas(self, highlightthickness=0,
                                bg=COLORS['card'])
        self.vsb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.vsb.pack(side='right', fill='y')
        self.canvas.bind('<Configure>', lambda e: self._render())
        self._empty()

    # ---------- 公共 ----------

    def add_result(self, title, metrics=None, paths=None, warns=None, ts=None):
        self.cards.append({'title': title, 'metrics': list(metrics or []),
                           'paths': list(paths or []), 'warns': list(warns or []),
                           'ts': ts})
        if len(self.cards) > _MAX_CARDS:
            self.cards.pop(0)
        self._render()

    def clear(self):
        self.cards.clear()
        self._render()

    # ---------- 渲染 ----------

    def _empty(self):
        ttk.Label(self.canvas, text='运行完成后结果显示在这里',
                  style='CardMuted.TLabel').place(relx=0.5, rely=0.35, anchor='center')

    def _render(self):
        for w in self.canvas.winfo_children():
            if w.winfo_class() != 'Scrollbar':
                w.destroy()
        self.canvas.delete('all')
        if not self.cards:
            self._empty()
            return
        body = ttk.Frame(self.canvas, style='Card.TFrame', padding=8)
        self.canvas.create_window(0, 0, anchor='nw', window=body,
                                  tags=('body',))
        self._body = body
        for card in reversed(self.cards):       # 最新在上
            self._build_card(body, card)
        body.update_idletasks()
        w = body.winfo_reqwidth()
        h = body.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, w, h))
        self.canvas.itemconfigure('body', width=max(self.canvas.winfo_width(), w))
        self.canvas.yview_moveto(0.0)

    def _build_card(self, parent, card):
        box = tk.Frame(parent, bd=1, relief='solid', bg=COLORS['card'],
                       highlightbackground=DIVIDER, highlightthickness=1)
        box.pack(fill='x', pady=(0, 8))
        head = tk.Frame(box, bg=COLORS['card'])
        head.pack(fill='x', padx=8, pady=(6, 2))
        tk.Label(head, text=card['title'], bg=COLORS['card'],
                 fg=COLORS['primary_dark'], font=FONT['bold'],
                 anchor='w').pack(side='left')
        if card['ts']:
            tk.Label(head, text=card['ts'], bg=COLORS['card'],
                     fg=COLORS['muted'], font=FONT['body']).pack(side='right')
        if card['metrics']:
            grid = tk.Frame(box, bg=COLORS['card'])
            grid.pack(fill='x', padx=8, pady=2)
            for col, (k, v) in enumerate(card['metrics']):
                cell = tk.Frame(grid, bg=COLORS['bg'])
                cell.grid(row=0, column=col, padx=3, sticky='ew')
                grid.columnconfigure(col, weight=1)
                tk.Label(cell, text=str(k), bg=COLORS['bg'], fg=COLORS['muted'],
                         font=FONT['body']).pack(anchor='center')
                tk.Label(cell, text=str(v), bg=COLORS['bg'],
                         fg=COLORS['primary_dark'],
                         font=FONT['bold']).pack(anchor='center')
        if card['paths']:
            for p in card['paths']:
                tk.Label(box, text='输出: %s' % p, bg=COLORS['card'],
                         fg=COLORS['text'], font=FONT['log'], anchor='w',
                         wraplength=280, justify='left').pack(fill='x', padx=8, pady=1)
        if card['warns']:
            for wtext in card['warns']:
                tk.Label(box, text='[!] %s' % wtext, bg=COLORS['card'],
                         fg=COLORS['warn'], font=FONT['body'], anchor='w',
                         wraplength=280, justify='left').pack(fill='x', padx=8, pady=1)
