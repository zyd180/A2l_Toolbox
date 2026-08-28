#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""更新A2L页签: 新版模型 A2L 同步进整车 A2L, 可选完成后自动更新地址."""

import time
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from gui.theme import COLORS, SPACE
from gui.common.widgets import file_row, PathListbox
from gui.tabs.base import BaseTab
from utils.config import FILE_TYPES
from utils.logger import timestamp, save_log_file
from utils import appstate
from core.elf_parser import parse_elf_symbols
from core.map_parser import parse_map_symbols
from core.a2l_parser import update_a2l_file
from core.sync_engine import sync_model_a2l


class SyncTab(BaseTab):

    TITLE = '  更新A2L  '
    DESC = ('将一个或多个新版模型 A2L 中的变量/标定量/曲线/MAP 更新进整车 A2L '
            '(保留已有 ECU 地址, GROUP 不同步不保留)')
    RUN_LABEL = '开始同步'

    def build(self):
        grp = ttk.Labelframe(self.body, text=' 文件选择 ',
                             style='Card.TLabelframe', padding=10)
        grp.pack(fill='x', pady=(0, SPACE['sm']))
        st = appstate.load_app_state()

        ttk.Label(grp, text='新模型A2L:', style='Card.TLabel').grid(
            row=0, column=0, sticky='nw', padx=(2, 6), pady=3)
        self.src_list = PathListbox(grp, height=4)
        self.src_list.grid(row=0, column=1, sticky='ew', padx=(0, 6), pady=3)
        for p in st.get('sync_sources', []):
            self.src_list.add_paths([p])
        btns = ttk.Frame(grp, style='Card.TFrame')
        btns.grid(row=0, column=2, sticky='n')
        ttk.Button(btns, text='添加...', command=self.browse_src).pack(fill='x', pady=(0, 3))
        ttk.Button(btns, text='移除', command=self.src_list.remove_selected).pack(fill='x', pady=(0, 3))
        ttk.Button(btns, text='清空', command=self.src_list.clear).pack(fill='x')

        self.tgt_var = tk.StringVar(value=st.get('sync_tgt', ''))
        self.out_var = tk.StringVar(value=st.get('sync_out', ''))
        file_row(grp, 1, 'Base A2L:', self.tgt_var, self.browse_tgt)
        file_row(grp, 2, 'A2L输出:', self.out_var, self.browse_out,
                 hint='默认覆盖整车 A2L (启用备份时先生成 .bak)')
        grp.columnconfigure(1, weight=1)

        opt = ttk.Frame(self.body, style='Card.TFrame')
        opt.pack(fill='x')
        self.purge_var = tk.BooleanVar(value=True)
        self.backup_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text='删除旧版有而新版没有的对象 (完全以新版为准)',
                        variable=self.purge_var,
                        style='Card.TCheckbutton').pack(side='left', padx=(4, SPACE['xl']))
        ttk.Checkbutton(opt, text='备份目标文件 (.bak)',
                        variable=self.backup_var,
                        style='Card.TCheckbutton').pack(side='left')

        # 内嵌可选步骤: 同步完成后对输出 A2L 整体刷新地址
        self.addr_after_var = tk.BooleanVar(value=False)
        self.sym_var = tk.StringVar(value=st.get('sync_sym', ''))
        ttk.Checkbutton(opt, text='同步完成后自动更新地址 (ELF/MAP → 输出 A2L)',
                        variable=self.addr_after_var, style='Card.TCheckbutton',
                        command=self._toggle_addr_row).pack(side='left', padx=(SPACE['xl'], 0))
        self.addr_row = ttk.Frame(self.body, style='Card.TFrame')
        file_row(self.addr_row, 0, '地址文件:', self.sym_var, self.browse_sym,
                 hint='按扩展名自动识别 ELF/MAP; 对同步输出整体执行地址更新')

    # ---------- 浏览 ----------
    def browse_src(self):
        paths = filedialog.askopenfilenames(title='选择新版模型 A2L (可多选)',
                                            filetypes=FILE_TYPES['a2l'])
        if paths:
            self.src_list.add_paths(paths)

    def browse_tgt(self):
        p = filedialog.askopenfilename(title='选择整车 A2L', filetypes=FILE_TYPES['a2l'])
        if p:
            self.tgt_var.set(p)
            if not self.out_var.get():
                self.out_var.set(p)

    def browse_out(self):
        p = filedialog.asksaveasfilename(title='保存输出 A2L', defaultextension='.a2l')
        if p:
            self.out_var.set(p)

    def browse_sym(self):
        p = filedialog.askopenfilename(title='选择 ELF/MAP 地址文件',
                                       filetypes=FILE_TYPES['elf'] + FILE_TYPES['map'])
        if p:
            self.sym_var.set(p)

    def _toggle_addr_row(self):
        if self.addr_after_var.get():
            self.addr_row.pack(fill='x', pady=(SPACE['xs'], 0))
        else:
            self.addr_row.pack_forget()

    # ---------- 运行 ----------
    def start(self):
        sources = self.src_list.get_all()
        tgt = self.tgt_var.get().strip()
        out = self.out_var.get().strip()
        if not sources or not tgt or not out:
            messagebox.showerror('错误', '请添加新模型 A2L 并填写 Base A2L 与输出路径')
            return
        for s in sources:
            if not Path(s).exists():
                messagebox.showerror('错误', f'新模型 A2L 不存在:\n{s}')
                return
        if not Path(tgt).exists():
            messagebox.showerror('错误', '整车 A2L 不存在')
            return
        backup = self.backup_var.get()
        purge = self.purge_var.get()
        sym = self.sym_var.get().strip() if self.addr_after_var.get() else ''
        if self.addr_after_var.get():
            if not sym:
                messagebox.showerror('错误', '已勾选自动更新地址, 请选择地址文件 (ELF/MAP)')
                return
            if not Path(sym).exists():
                messagebox.showerror('错误', f'地址文件不存在: {sym}')
                return
        if Path(out).resolve() == Path(tgt).resolve() and not backup:
            if not messagebox.askyesno('确认', '输出将覆盖整车 A2L 且未勾选备份, 是否继续?'):
                return

        self.app.begin_running()
        appstate.save_app_state(sync_sources=sources, sync_tgt=tgt, sync_out=out,
                                sync_sym=sym)
        threading.Thread(target=self._run, daemon=True,
                         args=(sources, tgt, out, purge, backup, sym)).start()

    def _run(self, sources, tgt, out, purge, backup, sym=''):
        start = time.time()
        try:
            self.app.clear_log()
            log = self.app.log_msg
            log('=' * 60)
            log('更新A2L - 处理日志')
            log('=' * 60)
            log(f'时间: {timestamp()}')
            log(f'新模型 A2L ({len(sources)} 个):')
            for s in sources:
                log(f'  - {s}')
            log(f'Base A2L:  {tgt}')
            log(f'A2L 输出:  {out}')
            log(f"删除旧版遗留对象: {'是' if purge else '否'}")
            log(f"备份目标文件:       {'是' if backup else '否'}")
            if sym:
                log(f'完成后自动更新地址: {sym}')
            log('=' * 60)

            # 依次同步: 第一个模型以 Base A2L 为基准, 后续模型基于上次输出继续
            all_stats = []
            cur_tgt = tgt
            for i, src in enumerate(sources):
                log(f'\n>>> [{i+1}/{len(sources)}] 同步模型: {Path(src).name}')
                self.app.root.after(0, self.app.status, 'running',
                                    '[%d/%d] 同步模型: %s'
                                    % (i + 1, len(sources), Path(src).name))
                stats = sync_model_a2l(src, cur_tgt, out, purge=purge,
                                       backup=(backup and i == 0), log=log)
                all_stats.append((Path(src).name, stats))
                cur_tgt = out

            elapsed = time.time() - start
            log(f"\n{'='*60}")
            log('同步统计')
            log(f"{'='*60}")
            tot_r = tot_a = tot_d = tot_s = tot_w = 0
            for name, stats in all_stats:
                line = (f"  {name}: 对象 {stats['src_total']}, "
                        f"替换/更新 {stats['replaced']}, 新增 {stats['added']}")
                if purge:
                    line += f", 删除 {stats['deleted']}"
                fstats = stats.get('function', {})
                if fstats.get('changed'):
                    line += (f", FUNCTION{'新增' if fstats.get('added') else '重建'}"
                             f": {fstats.get('name')}")
                log(line)
                tot_r += stats['replaced']
                tot_a += stats['added']
                tot_d += stats['deleted']
                tot_s += len(stats['kept_same'])
                tot_w += len(stats['kept_warn'])
            log('-' * 60)
            log(f'  合计: 替换/更新 {tot_r}, 新增 {tot_a}, 删除 {tot_d}, 保持未变 {tot_s}')
            if purge:
                log(f'  引用保留警告: {tot_w}')
            log(f'  处理耗时:     {elapsed:.2f}s')
            log(f"{'='*60}")

            # ---- 内嵌可选步骤: 对输出 A2L 整体刷新地址 ----
            addr_info = ''
            if sym:
                log('')
                log('>>> 自动更新地址: %s' % Path(sym).name)
                self.app.root.after(0, self.app.status, 'running',
                                    '更新地址: %s' % Path(sym).name)
                try:
                    stype = 'map' if sym.lower().endswith('.map') else 'elf'
                    symbols = (parse_map_symbols(sym) if stype == 'map'
                               else parse_elf_symbols(sym))
                    log('  地址文件类型: %s, 符号数: %d' % (stype.upper(), len(symbols)))
                    total, matched, updated, _x, astats = update_a2l_file(out, symbols, out)
                    un = astats.get('unmatched', 0)
                    log('  变量 %d | 匹配 %d | 地址更新 %d | 未匹配 %d'
                        % (total, matched, updated, un))
                    addr_info = f'\n地址更新: {updated}/{matched} (未匹配 {un})'
                except Exception as ae:
                    log(f'  地址更新失败: {ae}')
                    addr_info = '\n地址更新: 失败 (%s)' % ae

            log_path = save_log_file(self.app.log_buffer, self.app.log_queue, out)
            if log_path:
                log(f'\n日志已保存: {log_path}')

            self.app.root.after(0, self.app.status, 'ok',
                                f'完成! {len(sources)} 个模型: 更新 {tot_r}, 新增 {tot_a}, 删除 {tot_d}')
            purge_str = f'删除旧版遗留: {tot_d}\n' if purge else ''
            msg = (f'同步完成!\n\n模型数: {len(sources)}\n替换/更新: {tot_r}\n新增: {tot_a}\n'
                   f'{purge_str}保持未变: {tot_s}{addr_info}\n耗时: {elapsed:.2f}s\n\n输出: {out}')
            if tot_w:
                msg += f'\n\n注意: {tot_w} 个对象因块外仍有引用而未删除, 详见日志!'
            if log_path:
                msg += f'\n\n日志: {log_path}'
            self.app.info('完成', msg)
        except Exception as e:
            self.app.log_msg(f'错误: {e}\n{traceback.format_exc()}')
            self.app.root.after(0, self.app.status, 'err', f'出错: {e}')
            self.app.error('错误', str(e))
        finally:
            self.app.root.after(0, self.app.end_running)
