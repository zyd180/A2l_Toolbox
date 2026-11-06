#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""左侧窄条导航: 64px 竖排条目 (短标题), 选中主色高亮, 悬停反馈.

V2.7.0 工作台化改版: 由 170px 大卡片改为窄条, 给中央主区让出宽度.
对外接口不变: nav = SideNav(parent, on_select=cb); nav.add(标题, 副题); nav.select(i).
副题在窄条下不再显示 (信息移入页签内说明), 保留参数兼容旧调用.
"""

import tkinter as tk

from gui.theme import COLORS, FONT_FAMILY

_ITEM_W = 64


class SideNav(tk.Frame):
    """竖排窄条导航. select(i) 触发 on_select(i)."""

    def __init__(self, master, on_select, width=_ITEM_W):
        super().__init__(master, bg=COLORS['header'], width=width)
        self.pack_propagate(False)
        self.on_select = on_select
        self.active = -1
        self._items = []      # [card]

    def add(self, title, subtitle=''):
        i = len(self._items)
        card = tk.Label(self, text=title, bg=COLORS['header'], fg='white',
                        font=(FONT_FAMILY, 9, 'bold'), wraplength=_ITEM_W - 12,
                        justify='center', cursor='hand2', padx=4, pady=10)
        card.pack(fill='x', padx=4, pady=(6, 0))
        card.bind('<Button-1>', lambda e, i=i: self.select(i))
        card.bind('<Enter>', lambda e, i=i: self._hover(i, True))
        card.bind('<Leave>', lambda e, i=i: self._hover(i, False))
        self._items.append(card)
        return i

    def _hover(self, i, on):
        if i == self.active:
            return
        self._items[i].configure(bg=COLORS['nav_hover'] if on else COLORS['header'])

    def select(self, i):
        if not (0 <= i < len(self._items)):
            return
        if i == self.active:
            return
        if self.active != -1:
            self._paint(self.active, False)
        self._paint(i, True)
        self.active = i
        if self.on_select is not None:
            self.on_select(i)

    def _paint(self, i, on):
        self._items[i].configure(bg=COLORS['primary'] if on else COLORS['header'],
                                 fg='white')
