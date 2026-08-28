#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用控件 - CellGrid 可编辑网格 (色阶背景 / 选区 / TSV 复制粘贴)"""

import tkinter as tk
from tkinter import ttk


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


class CellGrid(tk.Frame):
    """基于 Canvas+Entry 的可编辑二维网格.

    - 单元格色阶背景 (colors[i][j] 为 0~1 比例, None 则不着色)
    - 点击选格, Shift+点击/拖选矩形区, Ctrl+C/V TSV 与 Excel 互通
    - 双击进入编辑, Return/FocusOut 提交 on_edit(r,c,text)

    注意: 事件必须绑定在单元格控件上而非 Canvas —— create_window 的
    子窗口会拦截其覆盖区域内的所有鼠标事件
    """

    CELL_W = 86
    CELL_H = 24

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
        self._cells = {}
        self._headers = {}
        self._anchor = None      # 选区锚点 (r,c)
        self._focus = None       # 当前格 (r,c)
        self._entry = None
        self._commit_cb = None
        self._top_band_text = ''
        self._corner_text = ''

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
        self.canvas.bind('<Button-1>', lambda e: None)
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
        self._destroy_cells()
        self._refresh()

    def refresh_value(self, r, c, text, color=None):
        if 0 <= r < self.n_rows and 0 <= c < self.n_cols:
            self.values[r][c] = text
            if color is not None:
                self.colors[r][c] = color
            w = self._cells.get((r, c))
            if w is not None:
                self._set_cell_text(w, text)
                self._style_cell(r, c, w)

    # ---------- 内部构建 ----------

    def _destroy_cells(self):
        for w in self._cells.values():
            w.destroy()
        self._cells.clear()
        for w in self._headers.values():
            w.destroy()
        self._headers.clear()

    def _make_cell(self, r, c):
        x0 = self.CELL_W * (c + 1)
        y0 = self.CELL_H * (r + 1) + getattr(self, '_yoff', 0)
        frm = tk.Frame(self.canvas, bd=1, relief='solid')
        lbl = tk.Label(frm, text='', font=('微软雅黑', 9), takefocus=0)
        lbl.place(x=0, y=0, width=self.CELL_W - 2, height=self.CELL_H - 2)
        self.canvas.create_window(x0 + 1, y0 + 1, anchor='nw', window=frm,
                                  width=self.CELL_W - 2, height=self.CELL_H - 2)
        # 事件绑定在单元格控件上 (Canvas 收不到子窗口区域的点击)
        for w in (frm, lbl):
            w.bind('<Button-1>', lambda e, rr=r, cc=c: self._select(rr, cc, False))
            w.bind('<Shift-Button-1>', lambda e, rr=r, cc=c: self._select(rr, cc, True))
            w.bind('<Double-Button-1>', lambda e, rr=r, cc=c: self._edit_at(rr, cc))
            w.bind('<B1-Motion>', lambda e, rr=r, cc=c: self._drag_to(rr, cc))
        return frm

    def _make_header(self, text, r, c):
        """r=-1 列头; c=-1 行头; r=c=-1 角头. editable_headers 时可双击编辑"""
        yoff = getattr(self, '_yoff', 0)
        frm = tk.Frame(self.canvas, bd=1, relief='solid')
        lbl = tk.Label(frm, text=str(text), font=('微软雅黑', 8),
                       bg='#dbe3ee', fg='#1f2937', takefocus=0)
        lbl.place(x=0, y=0, width=self.CELL_W - 2, height=self.CELL_H - 2)
        if r < 0 and c < 0:
            self.canvas.create_window(1, 1 + yoff, anchor='nw', window=frm,
                                      width=self.CELL_W - 2, height=self.CELL_H - 2)
            self._headers[('corner',)] = frm
            return frm
        if r < 0:
            kind, idx, x, y = 'col', c, self.CELL_W * (c + 1), 1 + yoff
        else:
            kind, idx, x, y = 'row', r, 1, self.CELL_H * (r + 1) + yoff
        self.canvas.create_window(x, y, anchor='nw', window=frm,
                                  width=self.CELL_W - 2, height=self.CELL_H - 2)
        self._headers[(kind, idx)] = frm
        if self.editable_headers and not self.readonly and self.on_edit_header:
            for w in (frm, lbl):
                w.bind('<Double-Button-1>',
                       lambda e, k=kind, ii=idx: self._edit_header(k, ii))
        return frm

    def _edit_header(self, kind, idx):
        """表头行内编辑 (轴点值), 提交回调 on_edit_header(kind, idx, text)"""
        if self.readonly or self._entry is not None:
            return
        frm = self._headers.get((kind, idx))
        if frm is None:
            return
        old = self.col_headers[idx] if kind == 'col' else self.row_headers[idx]
        entry = tk.Entry(frm, font=('微软雅黑', 8), justify='center',
                         bg='#fffbe6', highlightthickness=1,
                         highlightbackground='#2563eb', highlightcolor='#2563eb')

        def commit(event=None):
            if self._entry is None:
                return
            txt = entry.get().strip()
            self._entry = None
            self._commit_cb = None
            entry.destroy()
            if txt != old and self.on_edit_header:
                self.on_edit_header(kind, idx, txt)

        def cancel(event=None):
            self._entry = None
            self._commit_cb = None
            entry.destroy()

        entry.insert(0, old)
        entry.select_range(0, 'end')
        entry.place(x=0, y=0, width=self.CELL_W - 4, height=self.CELL_H - 4)
        entry.focus_set()
        entry.bind('<Return>', commit)
        entry.bind('<Escape>', cancel)
        entry.bind('<FocusOut>', commit)
        self._entry = entry
        self._commit_cb = commit

    def _style_cell(self, r, c, frm):
        frac = self.colors[r][c] if (r < len(self.colors) and c < len(self.colors[r])) else None
        bg = 'white' if frac is None else ramp_color(frac)
        frm.configure(bg=bg)
        in_sel = self._in_selection(r, c)
        fg = '#1d4ed8' if in_sel else '#1f2937'
        for ch in frm.winfo_children():
            ch.configure(bg=bg, fg=fg)

    def _in_selection(self, r, c):
        if not self._anchor or not self._focus:
            return False
        r0, r1 = sorted((self._anchor[0], self._focus[0]))
        c0, c1 = sorted((self._anchor[1], self._focus[1]))
        return r0 <= r <= r1 and c0 <= c <= c1

    def _refresh(self):
        self._destroy_cells()
        self._yoff = self.CELL_H if self._top_band_text else 0
        if self._yoff:
            band = tk.Label(self.canvas, text=self._top_band_text,
                            font=('微软雅黑', 8, 'bold'), bg='#e2e8f0',
                            fg='#334155', anchor='w', padx=6)
            self.canvas.create_window(self.CELL_W + 2, 1, anchor='nw', window=band,
                                      width=max(self.CELL_W * self.n_cols - 2, 100),
                                      height=self.CELL_H - 2)
        self._make_header(self._corner_text, -1, -1)
        for c in range(self.n_cols):
            self._make_header(self.col_headers[c] if c < len(self.col_headers) else c, -1, c)
        for r in range(self.n_rows):
            self._make_header(self.row_headers[r] if r < len(self.row_headers) else r, r, -1)
            for c in range(self.n_cols):
                frm = self._make_cell(r, c)
                self._set_cell_text(frm, self.values[r][c])
                self._style_cell(r, c, frm)
                self._cells[(r, c)] = frm
        w = self.CELL_W * (self.n_cols + 1) + 4
        h = self.CELL_H * (self.n_rows + 1) + self._yoff + 4
        self.canvas.configure(scrollregion=(0, 0, w, h))

    def _set_cell_text(self, frm, text):
        kids = frm.winfo_children()
        if kids:
            kids[0].configure(text=text)

    def _recolor(self):
        for (r, c), frm in self._cells.items():
            self._style_cell(r, c, frm)

    # ---------- 选择 / 编辑 ----------

    def _select(self, r, c, extend=False):
        self._commit_editor()
        self._focus = (r, c)
        if not extend:
            self._anchor = (r, c)
        self._recolor()

    def _drag_to(self, r, c):
        if self._anchor and (r, c) != self._focus:
            self._focus = (r, c)
            self._recolor()

    def _edit_at(self, r, c):
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
        frm = self._cells.get((r, c))
        if frm is None:
            return
        old = self.values[r][c]
        entry = tk.Entry(frm, font=('微软雅黑', 9), justify='center',
                         bg='#fffbe6', highlightthickness=1,
                         highlightbackground='#2563eb', highlightcolor='#2563eb')

        def commit(event=None):
            if self._entry is None:
                return
            txt = entry.get().strip()
            self._entry = None
            self._commit_cb = None
            entry.destroy()
            if txt != old:
                self._set_cell_text(frm, txt)
                if self.on_edit:
                    self.on_edit(r, c, txt)

        def cancel(event=None):
            self._entry = None
            self._commit_cb = None
            entry.destroy()

        entry.insert(0, old)
        entry.select_range(0, 'end')
        entry.place(x=0, y=0, width=self.CELL_W - 4, height=self.CELL_H - 4)
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
        if self._entry is not None:
            e, self._entry = self._entry, None
            self._commit_cb = None
            e.destroy()

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
