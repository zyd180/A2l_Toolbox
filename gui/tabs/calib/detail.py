#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""详情面板: 右停靠面板「详情」页 — 选中对象信息 + 已修改清单(点击定位).

此前对象详情散在编辑器标题行, "已修改 N 个"只是统计栏里的一个数字,
清单本身没有出口 —— 想找回改过哪个量只能逐个翻。这里集中两块:
  1. 选中对象: 名称/类型/数据类型/单位/限值/地址/脏格数
  2. 已修改对象: 可点击行, 点击后经 locate_cb 在主表格定位 (选中+滚动可见)

面板自身不持有会话引用, 由 CalibTab 推送数据 (set_object/set_dirty);
current_name / dirty_names 暴露为公共属性供契约测试断言。
"""

import tkinter as tk
from tkinter import ttk

from gui.theme import COLORS, FONT, DIVIDER


class DetailPanel(ttk.Frame):

    _FIELDS = ('类型', '数据类型', '单位', '限值', '地址', '已修改')

    def __init__(self, master, locate_cb=None):
        super().__init__(master, style='Card.TFrame')
        self.locate_cb = locate_cb
        self.current_name = None
        self.dirty_names = []

        ttk.Label(self, text='选中对象', style='CardMuted.TLabel').pack(
            anchor='w', padx=8, pady=(6, 0))
        self.name_lbl = tk.Label(self, text='(未选中)', bg=COLORS['card'],
                                 fg=COLORS['primary_dark'], font=FONT['bold'],
                                 anchor='w')
        self.name_lbl.pack(fill='x', padx=8)
        self._value_lbls = {}
        for key in self._FIELDS:
            row = tk.Frame(self, bg=COLORS['card'])
            row.pack(fill='x', padx=8, pady=1)
            tk.Label(row, text=key, bg=COLORS['card'], fg=COLORS['muted'],
                     font=FONT['body'], width=8, anchor='w').pack(side='left')
            lbl = tk.Label(row, text='-', bg=COLORS['card'], fg=COLORS['text'],
                           font=FONT['body'], anchor='w')
            lbl.pack(side='left', fill='x', expand=True)
            self._value_lbls[key] = lbl

        ttk.Separator(self).pack(fill='x', padx=8, pady=(6, 2))
        self.dirty_head = ttk.Label(self, text='已修改对象 (0)', style='CardMuted.TLabel')
        self.dirty_head.pack(anchor='w', padx=8)
        self._list = tk.Frame(self, bg=COLORS['card'])
        self._list.pack(fill='both', expand=True, padx=8, pady=(0, 6))
        self._empty_dirty()

    # ---------- 数据推送 (CalibTab 调用) ----------

    def set_object(self, info):
        """info: {name, 类型, 数据类型, 单位, 限值, 地址, 已修改} 或 None"""
        if not info:
            self.current_name = None
            self.name_lbl.configure(text='(未选中)')
            for lbl in self._value_lbls.values():
                lbl.configure(text='-')
            return
        self.current_name = info.get('name')
        self.name_lbl.configure(text=str(info.get('name', '-')))
        for key in self._FIELDS:
            self._value_lbls[key].configure(text=str(info.get(key, '-')))

    def set_dirty(self, names):
        """names: 已修改对象名列表 (按显示顺序)"""
        self.dirty_names = list(names)
        self.dirty_head.configure(text='已修改对象 (%d)' % len(names))
        for w in self._list.winfo_children():
            w.destroy()
        if not self.dirty_names:
            self._empty_dirty()
            return
        for name in self.dirty_names[:50]:      # 上限 50 行, 防长清单卡顿
            row = tk.Label(self._list, text='› ' + name, bg=COLORS['card'],
                           fg=COLORS['primary_dark'], font=FONT['log'],
                           anchor='w', cursor='hand2')
            row.pack(fill='x')
            row.bind('<Button-1>', lambda e, n=name: self.locate(n))

    def locate(self, name):
        if self.locate_cb is not None:
            self.locate_cb(name)

    def _empty_dirty(self):
        tk.Label(self._list, text='(无修改)', bg=COLORS['card'],
                 fg=COLORS['muted'], font=FONT['body'], anchor='w').pack(
            fill='x', pady=(2, 0))
