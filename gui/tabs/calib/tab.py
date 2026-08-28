#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在线标定页签 - 对标 INCA 的浏览/搜索/编辑主界面"""

import re
import time
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from utils.config import COLORS, FILE_TYPES
from utils.logger import timestamp, save_log_file
from utils import appstate
from core.calib_engine import CalibSession, format_value
from gui.tabs.base import BaseTab
from gui.tabs.calib.editors import open_editor


def _wild_to_regex(pattern):
    r = pattern.replace('*', '.*').replace('?', '.')
    return re.compile('^%s$' % r, re.IGNORECASE)


class CalibTab(BaseTab):

    TITLE = '  在线标定  '
    DESC = ''
    HAS_RUN = False          # 自包含页签: 不使用全局"开始"按钮

    def __init__(self, notebook, app):
        super().__init__(notebook, app)
        self.session = None
        self._editors = {}
        self._iid_map = {}
        self._filter_job = None
        self._loading = False
        self._build_ui()
        self._bind_shortcuts()

    # ---------- 界面 ----------

    def _build_ui(self):
        grp = ttk.Labelframe(self, text=' 文件选择 ', style='Card.TLabelframe', padding=8)
        grp.pack(fill='x')
        self.a2l_var = tk.StringVar()
        self.hex_var = tk.StringVar()
        state = appstate.load_app_state()
        self.a2l_var.set(state.get('last_a2l', ''))
        self.hex_var.set(state.get('last_hex', ''))
        for r, (label, var, cmd) in enumerate((
                ('A2L:', self.a2l_var, self.browse_a2l),
                ('HEX:', self.hex_var, self.browse_hex))):
            ttk.Label(grp, text=label, style='Card.TLabel').grid(row=r, column=0, padx=(2, 4))
            ttk.Entry(grp, textvariable=var).grid(row=r, column=1, sticky='ew', padx=(0, 6), pady=2)
            ttk.Button(grp, text='浏览...', command=cmd).grid(row=r, column=2)
        grp.columnconfigure(1, weight=1)

        btns = ttk.Frame(grp, style='Card.TFrame')
        btns.grid(row=0, column=3, rowspan=2, padx=(10, 0))
        self.load_btn = ttk.Button(btns, text='加载标定量',
                                   style='Primary.TButton', command=self.load_calibration)
        self.load_btn.pack(fill='x', pady=(0, 4))
        self.save_btn = ttk.Button(btns, text='保存 HEX (Ctrl+S)',
                                   command=self.save_hex, state='disabled')
        self.save_btn.pack(fill='x')

        # 数据集操作行
        ops = ttk.Frame(self, style='Card.TFrame')
        ops.pack(fill='x', pady=(6, 0))
        ttk.Label(ops, text='数据集:', style='Card.TLabel').pack(side='left')
        self.dcm_export_btn = ttk.Button(ops, text='导出 DCM', command=self.export_dcm,
                                         state='disabled')
        self.dcm_export_btn.pack(side='left', padx=(6, 4))
        self.dcm_import_btn = ttk.Button(ops, text='导入 DCM', command=self.import_dcm,
                                         state='disabled')
        self.dcm_import_btn.pack(side='left', padx=4)
        self.hex_cmp_btn = ttk.Button(ops, text='HEX 对比', command=self.compare_hex,
                                      state='disabled')
        self.hex_cmp_btn.pack(side='left', padx=4)
        ttk.Label(ops, text='(导入/导出均为整体一个撤销单元; 对比结果输出到日志)',
                  style='CardMuted.TLabel').pack(side='left', padx=(10, 0))

        bar = ttk.Frame(self, style='Card.TFrame')
        bar.pack(fill='x', pady=(6, 2))
        ttk.Label(bar, text='分组:', style='Card.TLabel').pack(side='left')
        self.group_mode = tk.StringVar(
            value=appstate.load_app_state().get('last_group_mode', 'FUNCTION'))
        for mode, label in (('FUNCTION', 'FUNCTION'), ('GROUP', 'GROUP'), ('FLAT', '平铺')):
            ttk.Radiobutton(bar, text=label, value=mode, variable=self.group_mode,
                            style='Card.TRadiobutton',
                            command=self.rebuild_tree).pack(side='left', padx=(2, 8))
        ttk.Label(bar, text='搜索:', style='Card.TLabel').pack(side='left', padx=(10, 2))
        self.search_var = tk.StringVar()
        ent = ttk.Entry(bar, textvariable=self.search_var, width=28)
        ent.pack(side='left')
        self.search_entry = ent
        self.search_var.trace_add('write', self._on_search_typed)
        ttk.Button(bar, text='清除', width=5,
                   command=lambda: self.search_var.set('')).pack(side='left', padx=(4, 12))
        self.only_dirty_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text='仅显示已修改', variable=self.only_dirty_var,
                        style='Card.TCheckbutton',
                        command=self.apply_filter).pack(side='left')
        self.stat_lbl = ttk.Label(bar, text='未加载', style='CardMuted.TLabel')
        self.stat_lbl.pack(side='right')

        body = ttk.Frame(self, style='Card.TFrame')
        body.pack(fill='both', expand=True, pady=(4, 0))

        tree_frame = ttk.Frame(body, style='Card.TFrame')
        tree_frame.pack(side='left', fill='both', padx=(0, 6))
        # 树自带 heading 行显示标题, 与右侧表格 header 同构 → 顶部自然对齐
        self.func_tree = ttk.Treeview(tree_frame, selectmode='browse', height=16)
        self.func_tree.heading('#0', text='分组浏览', anchor='w')
        self.func_tree.column('#0', width=190)
        self.func_tree.pack(fill='both', expand=True)
        self.func_tree.bind('<<TreeviewSelect>>', self.on_tree_select)

        table_frame = ttk.Frame(body, style='Card.TFrame')
        table_frame.pack(side='left', fill='both', expand=True)
        cols = ('name', 'value', 'orig', 'unit', 'type', 'addr', 'status')
        heads = ('名称', '当前值', '原始值', '单位', '类型', '地址', '状态')
        widths = (190, 110, 90, 60, 90, 100, 60)
        self.table = ttk.Treeview(table_frame, columns=cols, show='headings',
                                  height=16, selectmode='extended')
        for c, h, w in zip(cols, heads, widths):
            self.table.heading(c, text=h)
            self.table.column(c, width=w, anchor='w' if c == 'name' else 'center')
        self.table.tag_configure('dirty', foreground='#1d4ed8')
        self.table.grid(row=0, column=0, sticky='nsew')
        vsb = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=vsb.set)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.table.bind('<Double-1>', self.on_double_click)
        self.table.bind('<Return>', lambda e: self.open_selected())
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label='编辑', command=self.open_selected)
        menu.add_command(label='还原原始值', command=self.restore_selected)
        menu.add_command(label='复制名称', command=self.copy_names)
        self.table.bind('<Button-3>', lambda e: menu.tk_popup(e.x_root, e.y_root))

    def _bind_shortcuts(self):
        top = self.winfo_toplevel()

        def when_active():
            return self.winfo_ismapped() and self.session is not None

        # 返回 'break' 终止事件沿 bindtags 继续传播
        top.bind('<Control-s>', lambda e: (self.save_hex(), 'break')[1]
                 if when_active() else None)
        top.bind('<Control-f>', lambda e: (self.search_entry.focus_set(), 'break')[1]
                 if when_active() else None)
        top.bind('<Control-z>', lambda e: (self._undo(), 'break')[1]
                 if when_active() else None)
        top.bind('<Control-y>', lambda e: (self._redo(), 'break')[1]
                 if when_active() else None)

    # ---------- 文件 ----------

    def browse_a2l(self):
        p = filedialog.askopenfilename(title='选择 A2L 文件', filetypes=FILE_TYPES['a2l'])
        if p:
            self.a2l_var.set(p)

    def browse_hex(self):
        p = filedialog.askopenfilename(title='选择 HEX 文件', filetypes=FILE_TYPES['hex'] + FILE_TYPES['all'])
        if p:
            self.hex_var.set(p)

    def log_msg(self, msg):
        if hasattr(self.app, 'log_msg'):
            self.app.log_msg(msg)

    # ---------- 加载 ----------

    def load_calibration(self):
        a2l, hx = self.a2l_var.get().strip(), self.hex_var.get().strip()
        if not a2l or not hx:
            messagebox.showerror('错误', '请先选择 A2L 和 HEX 文件')
            return
        if not Path(a2l).exists() or not Path(hx).exists():
            messagebox.showerror('错误', '文件不存在')
            return
        if self._loading:
            return
        self._loading = True
        self.load_btn.config(state='disabled')
        self.app._begin_running() if hasattr(self.app, '_begin_running') else None
        threading.Thread(target=self._do_load, args=(a2l, hx), daemon=True).start()

    def _do_load(self, a2l, hx):
        try:
            self.log_msg('=' * 60)
            self.log_msg('在线标定 - 加载')
            self.log_msg(f'A2L: {a2l}\nHEX: {hx}')
            t0 = time.time()
            session = CalibSession.load(a2l, hx, log=self.log_msg)
            elapsed = time.time() - t0
            self.session = session
            n_read = sum(1 for o in session.objects.values() if o.addr and any(
                v is not None for v in session.read_object(o)))
            self.log_msg('  加载完成: 对象 %d, HEX 可读 %d, 耗时 %.1fs'
                         % (len(session.objects), n_read, elapsed))
            self.winfo_toplevel().after(0, self._after_load)
        except Exception as e:
            self.log_msg(f'错误: {e}\n{traceback.format_exc()}')
            self.winfo_toplevel().after(0, lambda: messagebox.showerror('错误', str(e)))
        finally:
            self._loading = False
            self.winfo_toplevel().after(0, lambda: self.load_btn.config(state='normal'))
            if hasattr(self.app, '_end_running'):
                self.winfo_toplevel().after(0, self.app._end_running)

    def _after_load(self):
        self.save_btn.config(state='normal')
        for b in (self.dcm_export_btn, self.dcm_import_btn, self.hex_cmp_btn):
            b.config(state='normal')
        appstate.save_app_state(last_a2l=self.a2l_var.get().strip(),
                                last_hex=self.hex_var.get().strip(),
                                last_group_mode=self.group_mode.get())
        self.rebuild_tree()
        self.refresh_all()

    # ---------- 查找/过滤 ----------

    def _get_obj(self, name):
        """按名取对象: 标定量或轴点"""
        s = self.session
        return s.objects.get(name) or s.axis_pts.get(name)

    def visible_objects(self):
        """可见对象 = 标定量 + 轴点 (AXIS_PTS 也是可标定对象)"""
        s = self.session
        if not s:
            return []
        pat = self.search_var.get().strip()
        rx = _wild_to_regex(pat) if pat else None
        pool = list(s.objects.values()) + list(s.axis_pts.values())
        out = []
        for o in sorted(pool, key=lambda x: x.name):
            if self.only_dirty_var.get() and not s.is_dirty(o):
                continue
            if rx is not None and not rx.match(o.name):
                continue
            out.append(o)
        return out

    def rebuild_tree(self):
        tree, s = self.func_tree, self.session
        tree.delete(*tree.get_children())
        self._iid_map.clear()
        if not s:
            return
        vis = {o.name for o in self.visible_objects()}
        mode = self.group_mode.get()

        def add_leaf(parent, name):
            iid = tree.insert(parent, 'end', text=name,
                              values=('obj:%s' % name), open=False)
            self._iid_map[iid] = name

        if mode == 'FLAT':
            root = tree.insert('', 'end', text='全部 (%d)' % len(vis),
                               values=('grp:__all__',), open=True)
            for n in sorted(vis):
                add_leaf(root, n)
        elif mode == 'FUNCTION':
            shown = set()
            for fname in sorted(s.functions):
                members = [m for m in s.functions[fname] if m in vis]
                if not members:
                    continue
                fid = tree.insert('', 'end', text='%s (%d)' % (fname, len(members)),
                                  values=('grp:%s' % fname), open=False)
                shown.update(members)
                for m in sorted(members):
                    add_leaf(fid, m)
            rest = [n for n in sorted(vis) if n not in shown]
            if rest:
                fid = tree.insert('', 'end', text='未分组(%d)' % len(rest),
                                  values=('grp:__ungrouped__',), open=False)
                for m in rest:
                    add_leaf(fid, m)
        else:
            shown = set()

            def add_group(gname, parent):
                g = s.groups.get(gname)
                members = [m for m in (g.members if g else []) if m in vis and m not in shown]
                kids = [c for c in (g.children if g else []) if c in s.groups]
                label = '%s (%d)' % (gname, len(members))
                gid = tree.insert(parent, 'end', text=label,
                                  values=('grp:%s' % gname), open=False)
                for m in sorted(members):
                    shown.add(m)
                    add_leaf(gid, m)
                for c in kids:
                    add_group(c, gid)
                return gid

            roots = [g.name for g in s.groups.values() if g.parent is None]
            for rn in sorted(roots):
                add_group(rn, '')
            rest = [n for n in sorted(vis) if n not in shown]
            if rest:
                fid = tree.insert('', 'end', text='未分组(%d)' % len(rest),
                                  values=('grp:__ungrouped__',), open=False)
                for m in rest:
                    add_leaf(fid, m)

    def _on_search_typed(self, *a):
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(250, self.apply_filter)

    def apply_filter(self):
        self._filter_job = None
        if not self.session:
            return
        prev_group = self.tree_group_selection()
        self.rebuild_tree()
        tops = self.func_tree.get_children('')
        # 抑制 selection_set 触发的事件: 显式填充值行(确定行), 避免时序竞态
        self._suppress_select_event = True
        try:
            if prev_group:
                self.select_group(prev_group)
            elif tops:
                self.func_tree.selection_set(tops[0])
            self.on_tree_select()
        finally:
            self._suppress_select_event = False

    def tree_group_selection(self):
        sel = self.func_tree.selection()
        if not sel:
            return None
        vals = self.func_tree.item(sel[0], 'values')
        return vals[0] if vals else None

    def select_group(self, key):
        for iid in self.func_tree.get_children(''):
            if self.func_tree.item(iid, 'values')[0] == key:
                self.func_tree.selection_set(iid)
                self.func_tree.see(iid)
                return

    def on_tree_select(self, event=None):
        if getattr(self, '_suppress_select_event', False):
            return
        sel = self.func_tree.selection()
        if not sel:
            return
        vals = self.func_tree.item(sel[0], 'values')
        key = vals[0] if vals else ''
        s = self.session
        if key.startswith('obj:'):
            objs = [self._get_obj(key[4:])]

        elif key == 'grp:__all__':
            objs = self.visible_objects()
        elif key == 'grp:__ungrouped__':
            grouped = set()
            if self.group_mode.get() == 'FUNCTION':
                for ms in s.functions.values():
                    grouped.update(ms)
            else:
                for g in s.groups.values():
                    grouped.update(g.members)
            objs = [o for o in self.visible_objects() if o.name not in grouped]
        else:
            gname = key[4:]
            if self.group_mode.get() == 'FUNCTION':
                names = set(s.functions.get(gname, []))
            else:
                names = self._group_descendants(gname)
            objs = [o for o in self.visible_objects() if o.name in names]
        self.fill_table(objs)

    def _group_descendants(self, gname):
        out = set()
        stack = [gname]
        while stack:
            g = self.session.groups.get(stack.pop())
            if not g:
                continue
            out.update(g.members)
            stack.extend(g.children)
        return out

    # ---------- 表格 ----------

    def fill_table(self, objs):
        self.table.delete(*self.table.get_children())
        for o in objs:
            self._append_row(o)

    def _append_row(self, o):
        s = self.session
        cur = s.read_object(o)
        dirty = len(s.dirty_cells(o))
        val_str = self._fmt_array(cur)
        orig = s.read_original(o) if dirty else None
        orig_str = self._fmt_array(orig) if dirty else ('-' if isinstance(cur, list) else val_str)
        shape_s = '' if o.shape == (1,) else '[%s]' % 'x'.join(map(str, o.shape))
        addr_s = '0x%08X' % o.addr if o.addr else '-'
        iid = self.table.insert('', 'end', iid=o.name, values=(
            o.name, val_str, orig_str if dirty else '', s.unit_of(o) or '',
            o.kind + shape_s, addr_s, ('● %d格' % dirty) if dirty else ''),
            tags=('dirty',) if dirty else '')

    @staticmethod
    def _fmt_array(vals):
        if vals is None:
            return '-'
        if not isinstance(vals, list):
            vals = [vals]
        shown = []
        for v in vals[:3]:
            shown.append('-' if v is None else format_value(v))
        if len(vals) > 3:
            return '[' + ', '.join(shown) + ', ...](%d)' % len(vals)
        return '[' + ', '.join(shown) + ']'

    def update_row(self, obj_name):
        s = self.session
        o = self._get_obj(obj_name)
        if o is None:
            return
        if self.table.exists(o.name):
            self.table.delete(o.name)
        vis = {x.name for x in self.visible_objects()}
        if o.name in vis:
            self._append_row(o)
        n_dirty = len(s.dirty_objects())
        self.stat_lbl.configure(text='标定量 %d | 轴点 %d | 已修改 %d | Undo栈 %d'
                                % (len(s.objects), len(s.axis_pts),
                                   n_dirty, len(s.undo_stack)))

    def refresh_all(self, obj_name=None):
        if not self.session:
            return
        if obj_name:
            self.update_row(obj_name)
        else:
            sel = self.table.selection()
            self.on_tree_select()
            if sel:
                keep = [i for i in sel if self.table.exists(i)]
                if keep:
                    self.table.selection_set(keep)
        s = self.session
        self.stat_lbl.configure(text='标定量 %d | 轴点 %d | 已修改 %d | Undo栈 %d'
                                % (len(s.objects), len(s.axis_pts),
                                   len(s.dirty_objects()), len(s.undo_stack)))
        # 同步刷新已打开的编辑器视图 (Ctrl+Z 焦点在主窗口时也保持编辑器内容一致)
        for name, dlg in list(self._editors.items()):
            if dlg.winfo_exists():
                try:
                    dlg.reload_data()
                except Exception:
                    pass
            else:
                self._editors.pop(name, None)

    # ---------- 编辑动作 ----------

    def on_double_click(self, event):
        self.open_selected()

    def open_selected(self):
        sel = self.table.selection()
        if not sel or not self.session:
            return
        name = sel[0]
        obj = self._get_obj(name)
        if obj is None:
            return
        dlg = self._editors.get(name)
        if dlg is not None and dlg.winfo_exists():
            dlg.lift()
            dlg.focus_force()
            return
        dlg = open_editor(self, obj)
        if dlg is not None:
            self._editors[name] = dlg

    def _editor_closed(self, name):
        self._editors.pop(name, None)

    def restore_selected(self):
        sel = self.table.selection()
        if not sel or not self.session:
            return
        n = 0
        for name in sel:
            o = self._get_obj(name)
            if o and self.session.restore_object(o):
                self.update_row(name)
                n += 1
        if n:
            self.log_msg('还原 %d 个对象' % n)

    def copy_names(self):
        names = '\n'.join(self.table.selection())
        if names:
            self.clipboard_clear()
            self.clipboard_append(names)

    def _undo(self):
        if not self.session:
            return
        if self.session.undo():
            self.refresh_all()
            self.log_msg('撤销 (Ctrl+Z)')
        else:
            self.log_msg('撤销: 已到初始状态, 无可撤销操作')

    def _redo(self):
        if not self.session:
            return
        if self.session.redo():
            self.refresh_all()
            self.log_msg('重做 (Ctrl+Y)')
        else:
            self.log_msg('重做: 无可重做操作')

    # ---------- 数据集管理 ----------

    def export_dcm(self):
        s = self.session
        if not s:
            return
        n_dirty = len(s.dirty_objects())
        if n_dirty:
            only_dirty = messagebox.askyesno(
                '导出范围',
                '当前有 %d 个已修改对象。\n\n是: 仅导出已修改对象\n否: 导出全部可读对象 (%d 个)'
                % (n_dirty, len(s.objects)))
        else:
            if not messagebox.askyesno('确认', '将导出全部可读对象 (%d 个), 是否继续?'
                                       % len(s.objects)):
                return
            only_dirty = False
        path = filedialog.asksaveasfilename(
            title='导出 DCM', defaultextension='.dcm',
            initialfile=Path(self.a2l_var.get().strip()).stem + '_cal.dcm',
            filetypes=FILE_TYPES['dcm'])
        if not path:
            return
        try:
            st = s.export_dcm(path, only_dirty=only_dirty, log=self.log_msg)
            self.log_msg('已导出 DCM: %s (%d 个对象, 跳过 %d)'
                         % (path, st['exported'], st['skipped']))
            self.app._status('ok', 'DCM 已导出') if hasattr(self.app, '_status') else None
            messagebox.showinfo('完成', '已导出 %d 个对象到:\n%s\n\n跳过 (值不可读): %d'
                                % (st['exported'], path, st['skipped']))
        except Exception as e:
            messagebox.showerror('错误', '导出失败: %s' % e)

    def import_dcm(self):
        s = self.session
        if not s:
            return
        path = filedialog.askopenfilename(title='选择 DCM 文件', filetypes=FILE_TYPES['dcm'])
        if not path:
            return
        if not messagebox.askyesno(
                '确认', '将把 DCM 数据集应用到当前标定量 (含轴点)。\n\n'
                       '超出限值的写入会被拒绝; 整次导入为一个撤销单元 (Ctrl+Z 可整体还原)。\n\n'
                       '文件: %s\n\n继续?' % path):
            return
        try:
            res = s.apply_dcm(path, log=self.log_msg)
            self.log_msg('DCM 导入: 应用 %d, 未匹配 %d, 错误 %d'
                         % (res['applied'], res['missing'], len(res['errors'])))
            self.refresh_all()
            self.app._status('ok', 'DCM 已导入') if hasattr(self.app, '_status') else None
            msg = ('已应用 %d 个对象\n未匹配 (A2L 无此对象): %d\n错误: %d\n\n'
                   '(Ctrl+Z 可整体还原)' % (res['applied'], res['missing'],
                                            len(res['errors'])))
            if res['errors']:
                msg += '\n\n错误样例:\n' + '\n'.join('%s: %s' % e for e in res['errors'][:5])
            messagebox.showinfo('完成', msg)
        except Exception as e:
            messagebox.showerror('错误', '导入失败: %s' % e)

    def compare_hex(self):
        s = self.session
        if not s:
            return
        path = filedialog.askopenfilename(title='选择要对比的 HEX 文件',
                                          filetypes=FILE_TYPES['hex'] + FILE_TYPES['all'])
        if not path:
            return
        try:
            res = s.compare_hex(path, log=self.log_msg)
            self.log_msg('=' * 60)
            self.log_msg('HEX 对比报告: 当前 vs %s' % path)
            self.log_msg('差异字节: %d (当前 %d 字节 vs 对方 %d 字节)'
                         % (res['diff_bytes'], res['total_self'], res['total_other']))
            self.log_msg('涉及对象: %d 个, 对象外差异: %d 字节'
                         % (len(res['objects']), res['unknown_bytes']))
            for name, kind, cells, total in res['objects'][:200]:
                self.log_msg('  [%s] %s: %d/%d 格不同' % (kind, name, cells, total))
            if len(res['objects']) > 200:
                self.log_msg('  ... 其余 %d 个对象略' % (len(res['objects']) - 200))
            self.log_msg('=' * 60)
            self.app._status('ok', '对比完成') if hasattr(self.app, '_status') else None
            messagebox.showinfo(
                '对比完成',
                '差异字节: %d\n涉及对象: %d 个\n对象外差异: %d 字节\n\n详见日志 (可"保存日志"导出)'
                % (res['diff_bytes'], len(res['objects']), res['unknown_bytes']))
        except Exception as e:
            messagebox.showerror('错误', '对比失败: %s' % e)

    # ---------- 保存 ----------

    def save_hex(self):
        s = self.session
        if not s:
            messagebox.showinfo('提示', '尚未加载标定量')
            return
        dirty = s.dirty_objects()
        if not dirty:
            messagebox.showinfo('提示', '没有修改')
            return
        hex_path = self.hex_var.get().strip()
        bak = Path(hex_path + '.bak')
        if not bak.exists():
            try:
                bak.write_bytes(Path(hex_path).read_bytes())
                self.log_msg('已自动备份原 HEX -> %s' % bak)
            except OSError:
                pass
        try:
            s.save_hex(hex_path)
            self.log_msg('已保存: %s (修改 %d 个对象)' % (hex_path, len(dirty)))
            self.app._status('ok', 'HEX 已保存') if hasattr(self.app, '_status') else None
            messagebox.showinfo('完成', '已保存到:\n%s\n\n修改对象: %d\n备份: %s'
                                % (hex_path, len(dirty), bak))
        except Exception as e:
            messagebox.showerror('错误', '保存失败: %s' % e)
