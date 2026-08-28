#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""左侧大卡片导航: 两行文字(主标题+副标题), 选中主色高亮, 悬停反馈."""

import tkinter as tk

from gui.theme import COLORS, FONT, FONT_FAMILY


class SideNav(tk.Frame):
    """竖排导航条. 用法: nav = SideNav(parent, on_select=i回调); nav.add(标题, 副题); nav.select(i)."""

    def __init__(self, master, on_select, width=150):
        super().__init__(master, bg=COLORS['header'], width=width)
        self.pack_propagate(False)
        self.on_select = on_select
        self.active = -1
        self._items = []      # (card, title, sub)
        tk.Label(self, text='导航', bg=COLORS['header'], fg=COLORS['header_sub'],
                 font=(FONT_FAMILY, 8), anchor='w', padx=10).pack(
            fill='x', pady=(10, 0))

    def add(self, title, subtitle=''):
        i = len(self._items)
        card = tk.Frame(self, bg=COLORS['header'], cursor='hand2',
                        padx=10, pady=8)
        card.pack(fill='x', padx=(8, 10), pady=(6, 0))
        t = tk.Label(card, text=title, bg=card['bg'], fg='white',
                     font=(FONT_FAMILY, 11, 'bold'), anchor='w')
        t.pack(fill='x')
        sub = None
        if subtitle:
            sub = tk.Label(card, text=subtitle, bg=card['bg'],
                           fg=COLORS['header_sub'], font=(FONT_FAMILY, 8),
                           anchor='w', justify='left')
            sub.pack(fill='x')
        for w in (card, t, sub):
            if w is not None:
                w.bind('<Button-1>', lambda e, i=i: self.select(i))
        card.bind('<Enter>', lambda e, i=i: self._hover(i, True))
        card.bind('<Leave>', lambda e, i=i: self._hover(i, False))
        self._items.append((card, t, sub))
        return i

    def _hover(self, i, on):
        if i == self.active:
            return
        card, t, sub = self._items[i]
        bg = COLORS['nav_hover'] if on else COLORS['header']
        card.configure(bg=bg)
        t.configure(bg=bg)
        if sub is not None:
            sub.configure(bg=bg)

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
        card, t, sub = self._items[i]
        bg = COLORS['primary'] if on else COLORS['header']
        fg = 'white' if on else 'white'
        fg_sub = COLORS['nav_sub_on'] if on else COLORS['header_sub']
        card.configure(bg=bg)
        t.configure(bg=bg, fg=fg)
        if sub is not None:
            sub.configure(bg=bg, fg=fg_sub)
