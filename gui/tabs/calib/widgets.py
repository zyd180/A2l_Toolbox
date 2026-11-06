#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用控件 - CellGrid 可编辑网格 (色阶背景 / 选区 / TSV 复制粘贴)

V2.7.0 虚拟化重写: 每格不再创建 Frame+Label 两个 Tk 子窗口 (几十×几十的 MAP
要建上千窗口, 打开编辑器明显卡顿), 改为 Canvas 单层绘制 (每格 2 个 canvas
item, 无窗口对象), 事件统一绑定在 Canvas 上按坐标命中。

公共 API 与旧版逐字兼容, 编辑器 (editors.py) 零改动:
    set_data / refresh_value / selection_rect / focus_cell /
    copy_selection / paste_from_clipboard / values / colors /
    n_rows / n_cols / row_headers / col_headers / CELL_W / CELL_H
"""

import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

from gui.theme import COLORS, DIVIDER


# 值 -> 颜色 (绿->黄->红 渐变, INCA 热图风格)
def ramp_color(frac):
    frac = 0.0 if frac != frac else min(1.0, max(0.0, frac))
    stops = [(0.0, (0, 144, 64)), (0.5, (255, 235, 120)), (1.0, (220, 60, 40))]
    for (f0, c0), (f1, c1) in zip(stops, stops[1:]):
        if frac <= f1:
            t = (frac - f0) / (f1 - f0) if f1 > f0 else 0.0
            r, g, b = (round(a + (b - a) * t) for a, b in zip(c0, c1))
            return '#%02x%02x%02x' % (r, g, b)
    return '#ffffff'


def parse_tsv(text):
    """TSV 文本 -> 二维列表"""
    rows = []
    for line in text.replace('\r\n', '\n').strip('\n').split('\n'):
        rows.append(line.split('\t'))
    return rows


# 视觉对齐 theme token (V2.7.0): 不再散落硬编码色值
_BORDER = DIVIDER                        # 单元格描边 (替代旧 Frame bd=1 relief=solid 观感)
_HDR_BG = COLORS['tab_idle']
_HDR_FG = COLORS['text']
_EDIT_BG = '#fffbe6'
_SEL_FG = COLORS['primary_dark']
_FG = COLORS['text']


class CellGrid(tk.Frame):
    """基于 Canvas 单层绘制的可编辑二维网格 (虚拟化, 每格 0 个子窗口).

    - 单元格色阶背景 (colors[i][j] 为 0~1 比例, None 则不着色)
    - 点击选格, Shift+点击/拖选矩形区, Ctrl+C/V TSV 与 Excel 互通
    - 双击进入编辑, Return/FocusOut 提交 on_edit(r,c,text)
    - 表头可双击编辑 (editable_headers 时), 提交 on_edit_header(kind, idx, text)
    """

    CELL_W = 86
    CELL_H = 24
    _MAX_TEXT_CHARS = 14    # 86px / 微软雅黑9 的安全显示宽度, 超长截断加省略号

    def __init__(self, master, n_rows=0, n_cols=0, row_headers=None,
                 col_headers=None, readonly=False, on_edit=None,
                 editable_headers=False, on_edit_header=None, **kw):
        super().__init__(master, **kw)
        self.readonly = readonly
        self.on_edit = on_edit
        self.editable_headers = editable_headers
        self.on_edit_header = on_edit_header
        self.n_rows = n_rows
        self.n_cols = n_cols
        self.row_headers = list(row_headers or [])
        self.col_headers = list(col_headers or [])
        self.values = [[''] * max(n_cols, 1) for _ in range(max(n_rows, 1))]
        self.colors = [[None] * max(n_cols, 1) for _ in range(max(n_rows, 1))]
        self._rect = {}         # (r,c) -> canvas 矩形 item id
        self._text = {}         # (r,c) -> canvas 文字 item id
        self._hdr_rect = {}     # ('col'/'row', i) -> header 矩形 item id
        self._hdr_text = {}
        self._anchor = None      # 选区锚点 (r,c)
        self._focus = None       # 当前格 (r,c)
        self._entry = None
        self._entry_win = None   # 编辑 Entry 的 create_window id
        self._commit_cb = None
        self._top_band_text = ''
        self._corner_text = ''
        self._yoff = 0
        self._font = tkfont.Font(family='微软雅黑', size=9)
        self._hdr_font = tkfont.Font(family='微软雅黑', size=8)

        self.canvas = tk.Canvas(self, highlightthickness=0, bg='#eef2f7')
        self.vsb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.hsb = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.vsb.grid(row=0, column=1, sticky='ns')
        self.hsb.grid(row=1, column=0, sticky='ew')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas.bind('<Configure>', lambda e: self._refresh())
        # 事件统一在 Canvas 上按坐标命中 (虚拟化后没有子窗口拦截问题)
        self.canvas.bind('<Button-1>', self._on_click)
        self.canvas.bind('<Double-Button-1>', self._on_double)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.bind('<Control-c>', lambda e: self.copy_selection())

    # ---------- 数据 ----------

    def set_data(self, values, colors=None, row_headers=None, col_headers=None,
                 top_band=None, corner_text=None):
        self._cancel_editor()
        self.values = [list(r) for r in values]
        self.n_rows = len(self.values)
        self.n_cols = len(self.values[0]) if self.values else 0
        self.colors = colors if colors is not None else \
            [[None] * self.n_cols for _ in range(self.n_rows)]
        if row_headers is not None:
            self.row_headers = list(row_headers)
        if col_headers is not None:
            self.col_headers = list(col_headers)
        if top_band is not None:
            self._top_band_text = top_band
        if corner_text is not None:
            self._corner_text = corner_text
        self._anchor = None
        self._focus = None
        self._refresh()

    def refresh_value(self, r, c, text, color=None):
        if 0 <= r < self.n_rows and 0 <= c < self.n_cols:
            self.values[r][c] = text
            if color is not None:
                self.colors[r][c] = color
            if (r, c) in self._rect:
                self._style_cell(r, c)

    # ---------- 内部绘制 ----------

    def _clip(self, s):
        s = str(s)
        if len(s) <= self._MAX_TEXT_CHARS:
            return s
        return s[:self._MAX_TEXT_CHARS - 1] + '…'

    def _refresh(self):
        for item in self.canvas.find_all():
            self.canvas.delete(item)
        self._rect.clear()
        self._text.clear()
        self._hdr_rect.clear()
        self._hdr_text.clear()
        if self._entry_win is not None:
            self.canvas.delete(self._entry_win)
            self._entry_win = None
        self._yoff = self.CELL_H if self._top_band_text else 0
        W, H = self.CELL_W, self.CELL_H

        # 顶部说明条 (单行, 保留为窗口控件以自动省略)
        if self._yoff:
            band = tk.Label(self.canvas, text=self._top_band_text,
                            font=('微软雅黑', 8, 'bold'), bg='#e2e8f0',
                            fg='#334155', anchor='w', padx=6)
            self.canvas.create_window(W + 2, 1, anchor='nw', window=band,
                                      width=max(W * self.n_cols - 2, 100),
                                      height=H - 2)
        # 表头行 / 列 / 角
        self._draw_header(self._corner_text, -1, -1)
        for c in range(self.n_cols):
            self._draw_header(self.col_headers[c] if c < len(self.col_headers) else c, -1, c)
        for r in range(self.n_rows):
            self._draw_header(self.row_headers[r] if r < len(self.row_headers) else r, r, -1)
            for c in range(self.n_cols):
                x0 = W * (c + 1)
                y0 = H * (r + 1) + self._yoff
                rect = self.canvas.create_rectangle(
                    x0 + 1, y0 + 1, x0 + W - 1, y0 + H - 1,
                    fill='white', outline=_BORDER)
                text = self.canvas.create_text(
                    x0 + W // 2, y0 + H // 2, text=self._clip(self.values[r][c]),
                    font=self._font, fill=_FG)
                self._rect[(r, c)] = rect
                self._text[(r, c)] = text
                self._style_cell(r, c)
        w = W * (self.n_cols + 1) + 4
        h = H * (self.n_rows + 1) + self._yoff + 4
        self.canvas.configure(scrollregion=(0, 0, w, h))

    def _draw_header(self, text, r, c):
        """r=-1 列头; c=-1 行头; r=c=-1 角头. editable_headers 时列/行头可双击编辑"""
        W, H = self.CELL_W, self.CELL_H
        yoff = self._yoff
        if r < 0 and c < 0:
            x, y = 1, 1 + yoff
            key = ('corner',)
        elif r < 0:
            x, y = W * (c + 1), 1 + yoff
            key = ('col', c)
        else:
            x, y = 1, H * (r + 1) + yoff
            key = ('row', r)
        rect = self.canvas.create_rectangle(x, y, x + W - 2, y + H - 2,
                                            fill=_HDR_BG, outline=_BORDER)
        tid = self.canvas.create_text(x + W // 2 - 1, y + H // 2 - 1,
                                      text=self._clip(text), font=self._hdr_font,
                                      fill=_HDR_FG)
        self._hdr_rect[key] = rect
        self._hdr_text[key] = tid

    def _style_cell(self, r, c):
        rect, text = self._rect.get((r, c)), self._text.get((r, c))
        if rect is None:
            return
        frac = self.colors[r][c] if (r < len(self.colors) and c < len(self.colors[r])) else None
        bg = 'white' if frac is None else ramp_color(frac)
        fg = _SEL_FG if self._in_selection(r, c) else _FG
        self.canvas.itemconfigure(rect, fill=bg)
        self.canvas.itemconfigure(text, fill=fg, text=self._clip(self.values[r][c]))

    def _recolor(self):
        for (r, c) in self._rect:
            self._style_cell(r, c)

    def _in_selection(self, r, c):
        if not self._anchor or not self._focus:
            return False
        r0, r1 = sorted((self._anchor[0], self._focus[0]))
        c0, c1 = sorted((self._anchor[1], self._focus[1]))
        return r0 <= r <= r1 and c0 <= c <= c1

    # ---------- 命中测试 ----------

    def _hit(self, x, y):
        """Canvas 坐标 -> ('cell',r,c) / ('col',i) / ('row',i) / ('corner',) / None"""
        W, H, yoff = self.CELL_W, self.CELL_H, self._yoff
        if x < 0 or y < 0:
            return None
        if x < W and y < yoff + H:
            return ('corner',)
        if y < yoff + H:
            c = int(x // W) - 1
            return ('col', c) if 0 <= c < self.n_cols else None
        if x < W:
            r = int((y - yoff) // H) - 1
            return ('row', r) if 0 <= r < self.n_rows else None
        r = int((y - yoff) // H) - 1
        c = int(x // W) - 1
        if 0 <= r < self.n_rows and 0 <= c < self.n_cols:
            return ('cell', r, c)
        return None

    def _on_click(self, e):
        hit = self._hit(e.x, e.y)
        if hit and hit[0] == 'cell':
            self._select(hit[1], hit[2], extend=bool(e.state & 0x0001))

    def _on_drag(self, e):
        hit = self._hit(e.x, e.y)
        if hit and hit[0] == 'cell' and self._anchor and (hit[1], hit[2]) != self._focus:
            self._focus = (hit[1], hit[2])
            self._recolor()

    def _on_double(self, e):
        hit = self._hit(e.x, e.y)
        if not hit:
            return
        if hit[0] == 'cell':
            self._edit_at(hit[1], hit[2])
        elif hit[0] in ('col', 'row') and self.editable_headers \
                and not self.readonly and self.on_edit_header:
            self._edit_header(hit[0], hit[1])

    # ---------- 选择 / 编辑 ----------

    def _select(self, r, c, extend=False):
        self._commit_editor()
        self._focus = (r, c)
        if not extend:
            self._anchor = (r, c)
        self._recolor()

    def _edit_at(self, r, c):
        self._commit_editor()
        self._focus = (r, c)
        if not self._anchor:
            self._anchor = (r, c)
        self._recolor()
        self._start_edit()

    def selection_rect(self):
        """当前选区 (r0,r1,c0,c1); 无焦点返回 None"""
        if not self._focus:
            return None
        r0, r1 = sorted((self._anchor[0], self._focus[0])) if self._anchor \
            else (self._focus[0], self._focus[0])
        c0, c1 = sorted((self._anchor[1], self._focus[1])) if self._anchor \
            else (self._focus[1], self._focus[1])
        return r0, r1, c0, c1

    def focus_cell(self):
        return self._focus

    def _start_edit(self):
        if self.readonly or self._entry is not None or self._focus is None:
            return
        r, c = self._focus
        if (r, c) not in self._rect:
            return
        old = self.values[r][c]
        x0 = self.CELL_W * (c + 1)
        y0 = self.CELL_H * (r + 1) + self._yoff
        entry = tk.Entry(self.canvas, font=('微软雅黑', 9), justify='center',
                         bg=_EDIT_BG, highlightthickness=1,
                         highlightbackground='#2563eb', highlightcolor='#2563eb')

        def commit(event=None):
            if self._entry is None:
                return
            txt = entry.get().strip()
            self._teardown_entry()
            if txt != old:
                if (r, c) in self._text:
                    self.canvas.itemconfigure(self._text[(r, c)],
                                              text=self._clip(txt))
                if self.on_edit:
                    self.on_edit(r, c, txt)

        def cancel(event=None):
            self._teardown_entry()

        entry.insert(0, old)
        entry.select_range(0, 'end')
        self._entry_win = self.canvas.create_window(
            x0 + 3, y0 + 3, anchor='nw', window=entry,
            width=self.CELL_W - 6, height=self.CELL_H - 6)
        entry.focus_set()
        entry.bind('<Return>', commit)
        entry.bind('<Escape>', cancel)
        entry.bind('<FocusOut>', commit)
        self._entry = entry
        self._commit_cb = commit

    def _teardown_entry(self):
        if self._entry is not None:
            self._entry.destroy()
            self._entry = None
        if self._entry_win is not None:
            self.canvas.delete(self._entry_win)
            self._entry_win = None
        self._commit_cb = None

    def _edit_header(self, kind, idx):
        """表头行内编辑 (轴点值), 提交回调 on_edit_header(kind, idx, text)"""
        if self.readonly or self._entry is not None:
            return
        if (kind, idx) not in self._hdr_rect:
            return
        if kind == 'col':
            old = self.col_headers[idx]
            x0, y0 = self.CELL_W * (idx + 1), 1 + self._yoff
        else:
            old = self.row_headers[idx]
            x0, y0 = 1, self.CELL_H * (idx + 1) + self._yoff
        entry = tk.Entry(self.canvas, font=('微软雅黑', 8), justify='center',
                         bg=_EDIT_BG, highlightthickness=1,
                         highlightbackground='#2563eb', highlightcolor='#2563eb')

        def commit(event=None):
            if self._entry is None:
                return
            txt = entry.get().strip()
            self._teardown_entry()
            if txt != old and self.on_edit_header:
                self.on_edit_header(kind, idx, txt)

        def cancel(event=None):
            self._teardown_entry()

        entry.insert(0, old)
        entry.select_range(0, 'end')
        self._entry_win = self.canvas.create_window(
            x0 + 2, y0 + 2, anchor='nw', window=entry,
            width=self.CELL_W - 4, height=self.CELL_H - 4)
        entry.focus_set()
        entry.bind('<Return>', commit)
        entry.bind('<Escape>', cancel)
        entry.bind('<FocusOut>', commit)
        self._entry = entry
        self._commit_cb = commit

    def _commit_editor(self):
        if self._commit_cb is not None:
            self._commit_cb()

    def _cancel_editor(self):
        self._teardown_entry()

    # ---------- 剪贴板 ----------

    def copy_selection(self):
        rect = self.selection_rect()
        if rect is None:
            return ''
        r0, r1, c0, c1 = rect
        lines = ['\t'.join(str(self.values[r][c]) for c in range(c0, c1 + 1))
                 for r in range(r0, r1 + 1)]
        text = '\n'.join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        return text

    def paste_from_clipboard(self):
        """从焦点格起按 TSV 粘贴, 返回 {(r,c): 文本}"""
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return {}
        if not text.strip():
            return {}
        self._commit_editor()
        rows = parse_tsv(text)
        fr, fc = self._focus or (0, 0)
        out = {}
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                r, c = fr + i, fc + j
                if 0 <= r < self.n_rows and 0 <= c < self.n_cols and val != '':
                    out[(r, c)] = val
        return out
