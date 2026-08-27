#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""标定量编辑器 - VALUE / CURVE / MAP / AXIS_PTS 四类编辑对话框 (对标 INCA)"""

import tkinter as tk
from tkinter import ttk, messagebox

from core.calib_engine import format_value
from gui.calib.widgets import CellGrid

try:
    import matplotlib
    matplotlib.use('TkAgg')
    matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial']
    matplotlib.rcParams['axes.unicode_minus'] = False
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


class EditorDialog(tk.Toplevel):
    """编辑器基类: 会话联动 / Undo-Redo / 刷新钩子"""

    def __init__(self, tab, obj, title):
        super().__init__(tab.winfo_toplevel())
        self.tab = tab
        self.session = tab.session
        self.obj = obj
        self.title('%s - %s' % (title, obj.name))
        self.transient(self.master)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Control-z>', lambda e: self._undo())
        self.bind('<Control-y>', lambda e: self._redo())
        self.bind('<Escape>', lambda e: self.close())

        head = ttk.Frame(self, padding=(10, 8, 10, 2))
        head.pack(fill='x')
        unit = self.session.unit_of(obj)
        lim = '[%s, %s]' % (format_value(obj.lower), format_value(obj.upper)) \
            if obj.lower is not None or obj.upper is not None else '-'
        info = ('名称: %s    类型: %s%s    数据类型: %s    单位: %s    限值: %s'
                % (obj.name, obj.kind,
                   ('x'.join(str(s) for s in obj.shape) if obj.shape != (1,) else ''),
                   obj.dtype, unit or '-', lim))
        ttk.Label(head, text=info, style='CardMuted.TLabel').pack(anchor='w')
        ttk.Separator(self).pack(fill='x', padx=10)
        # 返回 'break' 阻断事件继续传到主窗口的同名快捷键, 避免连撤两步
        self.bind('<Control-z>', self._on_undo_key)
        self.bind('<Control-y>', self._on_redo_key)
        self.bind('<Control-c>', self._on_copy)
        self.bind('<Control-v>', self._on_paste)

    def _on_undo_key(self, event=None):
        self._undo()
        return 'break'

    def _on_redo_key(self, event=None):
        self._redo()
        return 'break'

    def _fit_geometry(self, need_w, need_h, min_w=420, min_h=300):
        """窗口尺寸取"内容所需"与屏幕可用区92%的较小值, 尽量完整显示全部内容"""
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = max(min_w, min(int(need_w), int(sw * 0.92)))
        h = max(min_h, min(int(need_h), int(sh * 0.92)))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 4)
        self.geometry('%dx%d+%d+%d' % (w, h, x, y))

    def _on_copy(self, event=None):
        grid = getattr(self, 'grid', None)
        if grid is not None:
            grid.copy_selection()

    def _on_paste(self, event=None):
        if hasattr(self, 'paste_clipboard'):
            self.paste_clipboard()

    def _after_edit(self, errs):
        """写入后的公共刷新: 错误提示 + 重载网格 + 通知页签"""
        if errs:
            lines = []
            for e in errs[:5]:
                try:
                    lines.append('%s: %s' % tuple(e)
                                 if isinstance(e, (tuple, list)) else str(e))
                except Exception:
                    lines.append(str(e))
            messagebox.showwarning('警告', '\n'.join(lines), parent=self)
        self.reload_data()
        self.tab.refresh_all()

    # ---- 子类接口 ----

    def reload_data(self):
        raise NotImplementedError

    def close(self):
        self.tab._editor_closed(self.obj.name)
        self.destroy()

    # ---- 公共操作 ----

    def _undo(self):
        if self.session.undo():
            self.tab.refresh_all()      # refresh_all 会同步刷新本编辑器视图

    def _redo(self):
        if self.session.redo():
            self.tab.refresh_all()

    def op_buttons(self, parent, with_apply=False, on_apply=None):
        bar = ttk.Frame(parent)
        bar.pack(side='bottom', fill='x', pady=(4, 8))
        ttk.Button(bar, text='还原原始值', command=self.restore_original).pack(side='left')
        if with_apply:
            def apply_and_close():
                if (on_apply or (lambda: True))():
                    self.close()
            ttk.Button(bar, text='确定', command=apply_and_close).pack(side='right', padx=(6, 0))
            ttk.Button(bar, text='应用', command=on_apply).pack(side='right')
        ttk.Button(bar, text='关闭', command=self.close).pack(side='right')

    def restore_original(self):
        if self.session.restore_object(self.obj):
            self.reload_data()
            self.tab.refresh_all()
            self.tab.log_msg('已还原: %s' % self.obj.name)
        else:
            messagebox.showinfo('提示', '该对象没有修改', parent=self)


# ==================== 单值编辑器 ====================

class ValueEditor(EditorDialog):

    def __init__(self, tab, obj):
        super().__init__(tab, obj, '标定值')
        body = ttk.Frame(self, padding=12)
        body.pack(fill='both', expand=True)

        row = ttk.Frame(body)
        row.pack(fill='x', pady=(0, 6))
        ttk.Label(row, text='新值:').pack(side='left')
        lo, hi = obj.lower, obj.upper
        self.var = tk.StringVar()
        cur = self.session.read_object(obj)[0]
        self.var.set('' if cur is None else format_value(cur))
        sb_kw = dict(textvariable=self.var, width=14, font=('微软雅黑', 10, 'bold'))
        if lo is not None and hi is not None:
            step = max(abs(hi - lo) / 100.0, 10 ** -3)
            self.spin = ttk.Spinbox(row, from_=lo, to=hi, increment=('%.6g' % step),
                                    **sb_kw)
        else:
            self.spin = ttk.Spinbox(row, **sb_kw)
        self.spin.pack(side='left', padx=(6, 12))
        self.raw_lbl = ttk.Label(row, text='')
        self.raw_lbl.pack(side='left')

        if lo is not None and hi is not None and hi > lo:
            slider_row = ttk.Frame(body)
            slider_row.pack(fill='x', pady=(0, 6))
            self.scale = ttk.Scale(slider_row, from_=lo, to=hi,
                                   command=self._on_slide)
            self.scale.set(cur if cur is not None else lo)
            self.scale.pack(fill='x')
            self._sliding = False
            self.var.trace_add('write', self._on_typed)

        ttk.Label(body, text='提示: 输入后点击"应用"写入, 点击"确定"写入并关闭',
                  style='CardMuted.TLabel').pack(anchor='w')
        self.op_buttons(body, with_apply=True, on_apply=self._apply)
        self._update_raw()
        self._center()

    def _on_typed(self, *a):
        try:
            self.scale.set(float(self.var.get()))
        except (ValueError, tk.TclError):
            pass

    def _on_slide(self, val):
        self.var.set(format_value(float(val)))

    def _parse_input(self):
        try:
            return float(self.var.get())
        except ValueError:
            messagebox.showerror('错误', '请输入有效数值', parent=self)
            return None

    def _apply(self):
        v = self._parse_input()
        if v is None:
            return False
        errs = self.session.write_values(self.obj, [v], [0])
        if errs:
            messagebox.showerror('错误', '; '.join(str(e[1]) for e in errs), parent=self)
            return False
        self.reload_data()
        self.tab.refresh_all()
        return True

    def reload_data(self):
        cur = self.session.read_object(self.obj)[0]
        if cur is not None:
            self.var.set(format_value(cur))
        self._update_raw()

    def _update_raw(self):
        cur = self.session.read_object(self.obj)[0]
        self.raw_lbl.configure(text='当前: %s' %
                               ('-' if cur is None else format_value(cur, self.obj.fmt)))

    def _center(self):
        self.update_idletasks()
        w, h = 420, 220
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 3
        self.geometry('%dx%d+%d+%d' % (w, h, x, y))


# ==================== 曲线编辑器 ====================

class CurveEditor(EditorDialog):

    def __init__(self, tab, obj):
        super().__init__(tab, obj, '曲线')
        main = ttk.Frame(self, padding=(10, 6))
        main.pack(fill='both', expand=True)

        self.fig = None
        if HAS_MPL:
            self.fig = Figure(figsize=(5.2, 2.8), dpi=96)
            self.ax = self.fig.add_subplot(111)
            self.canvas_mpl = FigureCanvasTkAgg(self.fig, master=main)
            widget = self.canvas_mpl.get_tk_widget()
            widget.pack(fill='both', expand=True)
            bar = ttk.Frame(main)
            bar.pack(fill='x')
            NavigationToolbar2Tk(self.canvas_mpl, bar, pack_toolbar=False)
            bar.pack(fill='x')
        else:
            ttk.Label(main, text='(未安装 matplotlib, 无图形预览)').pack(anchor='w')

        self.grid = CellGrid(main, readonly=False, on_edit=self._on_cell_edit)
        self.grid.pack(fill='both', expand=True, pady=(6, 0))
        ttk.Label(main, text='提示: 双击单元格编辑, 回车提交; 拖选后可线性插值/复制粘贴',
                  style='CardMuted.TLabel').pack(anchor='w')

        bar2 = ttk.Frame(main)
        bar2.pack(fill='x', pady=(4, 6))
        ttk.Button(bar2, text='线性插值(选区)', command=self.interpolate).pack(side='left')
        ttk.Button(bar2, text='复制 Ctrl+C',
                   command=self.grid.copy_selection).pack(side='left', padx=(8, 0))
        ttk.Button(bar2, text='粘贴 Ctrl+V',
                   command=self.paste_clipboard).pack(side='left', padx=(4, 0))
        self.op_buttons(main)

        self.x_obj = None
        ax0 = obj.axes[0] if obj.axes else None
        if ax0 is not None and ax0.type_ == 'COM_AXIS' and ax0.ref in self.session.axis_pts:
            self.x_obj = self.session.axis_pts[ax0.ref]
        self.reload_data()
        self._center()

    def _center(self):
        n = self.grid.n_rows or getattr(self.obj, 'array_size', 1)
        plot_h = 300 if HAS_MPL else 0
        need_w = 640 if HAS_MPL else 420
        need_h = CellGrid.CELL_H * (n + 1) + plot_h + 160
        self._fit_geometry(need_w, need_h, min_w=720, min_h=520)

    def _axis_values(self):
        return self.session.read_axis(self.obj, 0)

    def reload_data(self):
        ys = self.session.read_object(self.obj)
        xs = self._axis_values()
        fmt = self.obj.fmt
        # X 列仅在轴对象存在且轴值可读时显示 (可编辑);
        # 轴值不可读 (如地址为 0x0000 占位) 时降级为行头索引
        have_x_col = self.x_obj is not None and any(v is not None for v in xs)
        self.y_col = 1 if have_x_col else 0
        rows, colors = [], []
        for i, v in enumerate(ys):
            y_txt = '' if v is None else format_value(v, fmt)
            if have_x_col:
                xv = xs[i] if i < len(xs) else None
                x_txt = '' if xv is None else format_value(xv)
                rows.append([x_txt, y_txt])
                colors.append([None, None])
            else:
                rows.append([y_txt])
                colors.append([None])
        if any(v is not None for v in xs):
            row_headers = [('%.5g' % x) if x is not None else '[%d]' % i
                           for i, x in enumerate(xs[:len(ys)])]
            row_headers += ['[%d]' % i for i in range(len(xs), len(ys))]
        else:
            row_headers = ['[%d]' % i for i in range(len(ys))]
        if self.x_obj is not None:
            band = 'X轴: %s' % self.x_obj.name
        elif self.obj.axes and self.obj.axes[0].type_ == 'FIX_AXIS':
            band = 'X轴: FIX_AXIS (隐式轴, 不可编辑)'
        else:
            band = ''
        self.grid.set_data(
            rows, colors=colors, row_headers=row_headers,
            col_headers=(['X轴', '值'] if have_x_col else ['值']),
            top_band=band)
        for k in self.session.dirty_cells(self.obj):
            if k < len(rows):
                self.grid.values[k][self.y_col] += ' *'
        self._redraw(xs, ys)

    def _matrix_and_colors(self):
        ys = self.session.read_object(self.obj)
        nums = [v for v in ys if v is not None]
        vmin = min(nums) if nums else 0.0
        vmax = max(nums) if nums else 1.0
        span = (vmax - vmin) or 1.0
        colors = [[(None if v is None else (v - vmin) / span)] for v in ys]
        return ys, colors

    def _redraw(self, xs, ys):
        if not HAS_MPL:
            return
        self.ax.clear()
        try:
            xi = list(range(len(ys)))
            if all(v is not None for v in ys):
                px = xs if all(v is not None for v in xs) else xi
                self.ax.plot(px, ys, '-o', color='#2563eb', markersize=4)
                self.ax.grid(True, alpha=0.3)
                self.ax.set_xlabel('X')
                self.ax.set_ylabel(self.session.unit_of(self.obj) or '')
        except Exception:
            pass
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas_mpl.draw_idle()

    def _on_cell_edit(self, r, c, text):
        try:
            v = float(text)
        except ValueError:
            self.reload_data()
            return
        if c == 0 and self.x_obj is not None and r < self.x_obj.array_size:
            errs = self.session.write_values(self.x_obj, [v], [r])
            self._after_edit([(self.x_obj.name, e) for e in errs])
        else:
            errs = self.session.write_values(self.obj, [v], [r])
            self._after_edit(errs)

    def _batch_write(self, edits):
        """edits: {(r,c):float} -> 按目标对象批量写入 (c=0 为 X 轴, 其余为 Y)"""
        jobs = {}
        for (r, c), v in edits.items():
            tgt = self.x_obj if (c == 0 and self.x_obj is not None) else self.obj
            if r >= tgt.array_size:
                continue
            jobs.setdefault(id(tgt), [tgt, [], []])
            jobs[id(tgt)][1].append(r)
            jobs[id(tgt)][2].append(v)
        errs = []
        for tgt, idxs, vals in jobs.values():
            arr = [None] * tgt.array_size
            for k, v in zip(idxs, vals):
                arr[k] = v
            errs.extend((tgt.name, e) for e in
                        self.session.write_values(tgt, arr, idxs))
        self._after_edit(errs)

    def interpolate(self):
        rect = self.grid.selection_rect()
        if rect is None:
            return
        _, r1, _, r2 = rect
        col = self.y_col if self.x_obj is not None else 0
        if r2 - r1 < 2:
            messagebox.showinfo('提示', '请先选中至少 3 行', parent=self)
            return
        try:
            v0 = float(self.grid.values[r1][col])
            v1 = float(self.grid.values[r2][col])
        except (ValueError, IndexError):
            messagebox.showerror('错误', '选区首末值需为有效数字', parent=self)
            return
        arr = [None] * self.obj.array_size
        idxs = []
        n = r2 - r1
        for i, r in enumerate(range(r1, r2 + 1)):
            if r < self.obj.array_size:
                arr[r] = v0 + (v1 - v0) * i / n
                idxs.append(r)
        errs = self.session.write_values(self.obj, arr, idxs)
        self._after_edit(errs)
        self.tab.log_msg('线性插值: %s [%d..%d]' % (self.obj.name, r1, r2))

    def paste_clipboard(self):
        edits = self.grid.paste_from_clipboard()
        if not edits:
            return
        conv = {}
        for (r, c), t in edits.items():
            try:
                conv[(r, min(c, self.grid.n_cols - 1))] = float(t)
            except ValueError:
                continue
        self._batch_write(conv)

    def copy_shortcut(self):
        self.grid.copy_selection()


# ==================== MAP 编辑器 ====================

class MapEditor(EditorDialog):

    def __init__(self, tab, obj):
        super().__init__(tab, obj, 'MAP' if len(obj.shape) == 2 else '数组')
        if len(obj.shape) == 2:
            self.nx, self.ny = obj.shape
        else:
            # VAL_BLK 等一维数组: 显示为纵向向量
            self.nx, self.ny = 1, max(obj.array_size, 1)
        self.is_1d = len(obj.shape) != 2
        # 行/列轴对应的 AXIS_PTS 对象 (仅 COM_AXIS 可编辑轴值)
        self.x_obj = self.y_obj = None
        if len(obj.axes) > 0 and obj.axes[0].type_ == 'COM_AXIS' \
                and obj.axes[0].ref in self.session.axis_pts:
            self.x_obj = self.session.axis_pts[obj.axes[0].ref]
        if len(obj.axes) > 1 and obj.axes[1].type_ == 'COM_AXIS' \
                and obj.axes[1].ref in self.session.axis_pts:
            self.y_obj = self.session.axis_pts[obj.axes[1].ref]
        editable_hdr = any(o is not None and o.addr for o in (self.x_obj, self.y_obj))

        main = ttk.Frame(self, padding=(10, 6))
        main.pack(fill='both', expand=True)

        self.fig = None
        self._cbar = None
        if HAS_MPL:
            self.fig = Figure(figsize=(4.6, 3.0), dpi=96)
            self.ax = self.fig.add_subplot(111)
            self.canvas_mpl = cv = FigureCanvasTkAgg(self.fig, master=main)
            cv.get_tk_widget().pack(fill='both')
            NavigationToolbar2Tk(cv, ttk.Frame(main), pack_toolbar=False)
        else:
            ttk.Label(main, text='(未安装 matplotlib, 无热图预览)').pack(anchor='w')

        self.grid = CellGrid(main, readonly=False, on_edit=self._on_cell_edit,
                             editable_headers=editable_hdr,
                             on_edit_header=self._on_header_edit)
        self.grid.pack(fill='both', expand=True, pady=(6, 0))
        ttk.Label(main, text='提示: 双击数据格或行/列轴头编辑, 回车提交; 拖选后可行/列插值、复制粘贴',
                  style='CardMuted.TLabel').pack(anchor='w')

        bar2 = ttk.Frame(main)
        bar2.pack(fill='x', pady=(4, 6))
        ttk.Button(bar2, text='行插值', command=lambda: self.interpolate(axis='row')).pack(side='left')
        if not self.is_1d:
            ttk.Button(bar2, text='列插值',
                       command=lambda: self.interpolate(axis='col')).pack(side='left', padx=(6, 0))
        ttk.Button(bar2, text='复制 Ctrl+C',
                   command=self.grid.copy_selection).pack(side='left', padx=(12, 0))
        ttk.Button(bar2, text='粘贴 Ctrl+V',
                   command=self.paste_clipboard).pack(side='left', padx=(4, 0))
        self.op_buttons(main)

        self.reload_data()
        self._center()

    def _center(self):
        cw, ch = CellGrid.CELL_W, CellGrid.CELL_H
        # 内容所需宽 = 列数 + 角格列, 高 = 行数 + 热图区 + 工具行/提示/按钮
        need_w = cw * (self.nx + 1) + 56
        if HAS_MPL:
            need_w = max(need_w, 600 if not self.is_1d else 520)
            plot_h = 310
        else:
            plot_h = 0
        need_h = ch * (self.ny + 1) + plot_h + 170
        self._fit_geometry(need_w, need_h, min_w=760, min_h=520)

    def reload_data(self):
        vals = self.session.read_object(self.obj)
        nums = [v for v in vals if v is not None]
        vmin = min(nums) if nums else 0.0
        vmax = max(nums) if nums else 1.0
        span = (vmax - vmin) or 1.0
        fmt = self.obj.fmt
        xs = self.session.read_axis(self.obj, 0)
        ys = self.session.read_axis(self.obj, 1) if len(self.obj.axes) > 1 else []

        matrix = [[''] * self.nx for _ in range(self.ny)]
        colors = [[None] * self.nx for _ in range(self.ny)]
        for j in range(self.ny):
            for i in range(self.nx):
                k = self.session.grid_to_flat(self.obj, j, i)
                if k < len(vals) and vals[k] is not None:
                    matrix[j][i] = format_value(vals[k], fmt)
                    colors[j][i] = (vals[k] - vmin) / span
        row_h = [('%.5g' % y) if y is not None and j < len(ys) else '[%d]' % j
                 for j, y in enumerate(list(ys) + [None] * (self.ny - len(ys)))]
        col_h = [('%.5g' % x) if x is not None and i < len(xs) else '[%d]' % i
                 for i, x in enumerate(list(xs) + [None] * (self.nx - len(xs)))]
        if self.is_1d:
            band, corner = '', ''
        else:
            xref = self.x_obj.name if self.x_obj else (
                'FIX_AXIS (隐式)' if self.obj.axes and self.obj.axes[0].type_ == 'FIX_AXIS' else '-')
            yref = self.y_obj.name if self.y_obj else (
                'FIX_AXIS (隐式)' if len(self.obj.axes) > 1
                and self.obj.axes[1].type_ == 'FIX_AXIS' else '-')
            band = '列 = X轴: %s      行 = Y轴: %s' % (xref, yref)
            corner = 'Y \\ X'
        self.grid.set_data(matrix, colors=colors,
                           row_headers=row_h, col_headers=col_h,
                           top_band=band, corner_text=corner)
        for k in self.session.dirty_cells(self.obj):
            r, c = self.session.flat_to_grid(self.obj, k)
            if r < self.ny and c < self.nx:
                self.grid.values[r][c] += ' *'
        self._redraw(vals, vmin, vmax)

    def _redraw(self, vals, vmin, vmax):
        if not HAS_MPL:
            return
        self.ax.clear()
        try:
            if self.is_1d:
                idx = list(range(len(vals)))
                self.ax.bar(idx, [v if v is not None else 0 for v in vals],
                            color='#2563eb', width=0.6)
                self.ax.grid(True, axis='y', alpha=0.3)
                self.ax.set_xlabel('索引')
            else:
                img = [[vals[self.session.grid_to_flat(self.obj, j, i)]
                        for i in range(self.nx)] for j in range(self.ny)]
                im = self.ax.imshow(img, origin='lower', aspect='auto',
                                    cmap='viridis', interpolation='nearest')
                if self._cbar is None:
                    self._cbar = self.fig.colorbar(im, ax=self.ax)
                else:
                    self._cbar.update_normal(im)
                self.ax.set_xlabel('X')
                self.ax.set_ylabel('Y')
        except Exception:
            pass
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        # draw_idle 必须独立于布局异常执行, 否则热图不会实时刷新
        self.canvas_mpl.draw_idle()

    def _on_cell_edit(self, r, c, text):
        try:
            v = float(text)
        except ValueError:
            self.reload_data()
            return
        k = self.session.grid_to_flat(self.obj, r, c)
        errs = self.session.write_values(self.obj, [v], [k])
        self._after_edit(errs)

    def _on_header_edit(self, kind, idx, text):
        """双击行/列轴头编辑轴点值, 写回对应 AXIS_PTS 对象"""
        try:
            v = float(text)
        except ValueError:
            self.reload_data()
            return
        tgt = self.x_obj if kind == 'col' else self.y_obj
        if tgt is None:
            messagebox.showinfo('提示', '该轴无关联的 AXIS_PTS 对象 (STD_AXIS/FIX_AXIS), 轴值不可编辑',
                                parent=self)
            self.reload_data()
            return
        if not tgt.addr:
            messagebox.showwarning('警告',
                                   '轴对象 %s 的 ECU 地址为 0x0000 占位, 请先在「地址映射」页签更新地址'
                                   % tgt.name, parent=self)
            self.reload_data()
            return
        if idx >= tgt.array_size:
            return
        errs = self.session.write_values(tgt, [v], [idx])
        self._after_edit(errs)

    def paste_clipboard(self):
        edits = self.grid.paste_from_clipboard()
        if not edits:
            return
        arr = [None] * self.obj.array_size
        idxs = []
        for (r, c), t in edits.items():
            try:
                k = self.session.grid_to_flat(self.obj, r, c)
                if k < self.obj.array_size:
                    arr[k] = float(t)
                    idxs.append(k)
            except ValueError:
                continue
        errs = self.session.write_values(self.obj, arr, idxs)
        self._after_edit(errs)

    def interpolate(self, axis='row'):
        rect = self.grid.selection_rect()
        if rect is None:
            return
        r1, r2, c1, c2 = rect
        if axis == 'row':
            a, b = r1, r2
            fixed = (c1 + c2) // 2
        else:
            a, b = c1, c2
            fixed = (r1 + r2) // 2
        if b - a < 2:
            messagebox.showinfo('提示', '请选中至少 3 格', parent=self)
            return
        try:
            va = float(self.grid.values[a][fixed])
            vb = float(self.grid.values[b][fixed])
        except ValueError:
            messagebox.showerror('错误', '选区首末值需为有效数字', parent=self)
            return
        arr = [None] * self.obj.array_size
        idxs = []
        n = b - a
        for t in range(a, b + 1):
            v = va + (vb - va) * (t - a) / n
            r, c = (t, fixed) if axis == 'row' else (fixed, t)
            k = self.session.grid_to_flat(self.obj, r, c)
            if k < self.obj.array_size:
                arr[k] = v
                idxs.append(k)
        errs = self.session.write_values(self.obj, arr, idxs)
        self._after_edit(errs)
        self.tab.log_msg('%s插值: %s' % (('行' if axis == 'row' else '列'), self.obj.name))


# ==================== 轴点编辑器 ====================

class AxisEditor(EditorDialog):

    def __init__(self, tab, obj):
        super().__init__(tab, obj, '轴点')
        main = ttk.Frame(self, padding=(10, 6))
        main.pack(fill='both', expand=True)
        self.grid = CellGrid(main, readonly=False, on_edit=self._on_cell_edit)
        self.grid.pack(fill='both', expand=True)
        self.op_buttons(main)
        self.reload_data()
        self._fit_geometry(360, CellGrid.CELL_H * (obj.array_size + 2) + 130,
                           min_w=360, min_h=280)

    def reload_data(self):
        vals = self.session.read_object(self.obj)
        fmt = self.obj.fmt
        rows = [[('' if v is None else format_value(v, fmt))] for v in vals]
        self.grid.set_data(rows, colors=[[None]] * len(vals),
                           row_headers=['[%d]' % i for i in range(len(vals))],
                           col_headers=['轴值'])

    def _on_cell_edit(self, r, c, text):
        try:
            v = float(text)
        except ValueError:
            self.reload_data()
            return
        errs = self.session.write_values(self.obj, [v], [r])
        if errs:
            messagebox.showwarning('警告', str(errs[0][1]), parent=self)
        self.reload_data()
        self.tab.refresh_all()


def open_editor(tab, obj):
    """按对象类型打开对应编辑器, 返回对话框实例"""
    kind = getattr(obj, 'kind', 'VALUE')
    if kind == 'AXIS_PTS':
        dlg = AxisEditor(tab, obj)
    elif kind == 'VALUE':
        dlg = ValueEditor(tab, obj)
    elif kind == 'CURVE':
        dlg = CurveEditor(tab, obj)
    elif kind in ('MAP', 'VAL_BLK'):
        dlg = MapEditor(tab, obj)
    else:
        messagebox.showinfo('提示', '暂不支持编辑类型: %s' % kind)
        return None
    return dlg
