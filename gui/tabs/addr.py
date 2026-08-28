#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""地址映射页签: ELF/MAP 符号 → 更新 A2L 变量地址."""

import time
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from gui.theme import SPACE
from gui.common.widgets import file_row
from gui.tabs.base import BaseTab
from utils.config import FILE_TYPES
from utils.logger import timestamp, save_log_file
from utils import appstate
from core.elf_parser import parse_elf_symbols
from core.map_parser import parse_map_symbols
from core.a2l_parser import extract_a2l_variables, update_a2l_file


class AddrTab(BaseTab):

    TITLE = '  地址映射  '
    DESC = '根据 ELF/MAP 文件中的符号地址, 更新 A2L 中变量的 ECU 地址 (可选删除未匹配变量)'
    RUN_LABEL = '开始更新'
    HAS_TEST = True

    def build(self):
        self.symbols = None
        st = appstate.load_app_state()

        grp_src = ttk.Labelframe(self.body, text=' 符号源 ',
                                 style='Card.TLabelframe', padding=10)
        grp_src.pack(fill='x', pady=(0, SPACE['sm']))
        self.src_type_var = tk.StringVar(value='elf')
        ttk.Radiobutton(grp_src, text='ELF 文件', variable=self.src_type_var,
                        value='elf', style='Card.TRadiobutton').grid(
            row=0, column=1, sticky='w', padx=(0, SPACE['xl']), pady=(0, SPACE['xs']))
        ttk.Radiobutton(grp_src, text='MAP 文件', variable=self.src_type_var,
                        value='map', style='Card.TRadiobutton').grid(
            row=0, column=2, sticky='w', pady=(0, SPACE['xs']))
        self.src_var = tk.StringVar(value=st.get('addr_src', ''))
        file_row(grp_src, 1, '源文件:', self.src_var, self.browse_src)

        grp_io = ttk.Labelframe(self.body, text=' A2L 文件 ',
                                style='Card.TLabelframe', padding=10)
        grp_io.pack(fill='x', pady=(0, SPACE['sm']))
        self.a2l_in_var = tk.StringVar(value=st.get('addr_in', ''))
        self.a2l_out_var = tk.StringVar(value=st.get('addr_out', ''))
        file_row(grp_io, 0, 'A2L输入:', self.a2l_in_var, self.browse_a2l_in)
        file_row(grp_io, 1, 'A2L输出:', self.a2l_out_var, self.browse_a2l_out)

        opt = ttk.Frame(self.body, style='Card.TFrame')
        opt.pack(fill='x')
        self.remove_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text='删除A2L中有但ELF/MAP中没有的变量',
                        variable=self.remove_var,
                        style='Card.TCheckbutton').pack(side='left', padx=SPACE['xs'])

    # ---------- 浏览 ----------
    def browse_src(self):
        ft = FILE_TYPES['elf'] if self.src_type_var.get() == 'elf' else FILE_TYPES['map']
        p = filedialog.askopenfilename(title='选择源文件', filetypes=ft + FILE_TYPES['all'])
        if p:
            self.src_var.set(p)

    def browse_a2l_in(self):
        p = filedialog.askopenfilename(title='选择A2L文件', filetypes=FILE_TYPES['a2l'])
        if p:
            self.a2l_in_var.set(p)
            if not self.a2l_out_var.get():
                pp = Path(p)
                self.a2l_out_var.set(str(pp.parent / f'{pp.stem}_updated{pp.suffix}'))

    def browse_a2l_out(self):
        p = filedialog.asksaveasfilename(title='保存A2L', defaultextension='.a2l')
        if p:
            self.a2l_out_var.set(p)

    # ---------- 测试解析 ----------
    def test(self):
        src = self.src_var.get().strip()
        a2l = self.a2l_in_var.get().strip()
        if not src or not a2l:
            messagebox.showerror('错误', '请先选择文件')
            return
        self.app.clear_log()
        self.app.log_msg('=== 测试解析 ===\n')
        stype = self.src_type_var.get()
        try:
            self.symbols = (parse_elf_symbols(src) if stype == 'elf'
                            else parse_map_symbols(src))
            self.app.log_msg(f'[{stype.upper()}] 符号数: {len(self.symbols)}')
            for n, a in list(self.symbols.items())[:10]:
                self.app.log_msg(f'  {n:40s} 0x{a:08X}')
        except Exception as e:
            self.app.log_msg(f'解析失败: {e}')
            return

        self.app.log_msg('\n[A2L] 解析变量...')
        try:
            variables, _ = extract_a2l_variables(a2l)
            self.app.log_msg(f'变量数: {len(variables)}')
            for v in variables[:5]:
                self.app.log_msg(f"  {v['name']:40s} 行{v['addr_line']}")
        except Exception as e:
            self.app.log_msg(f'解析失败: {e}')

    # ---------- 运行 ----------
    def start(self):
        src = self.src_var.get().strip()
        a2l_in = self.a2l_in_var.get().strip()
        a2l_out = self.a2l_out_var.get().strip()
        if not all([src, a2l_in, a2l_out]):
            messagebox.showerror('错误', '请填写所有路径')
            return
        if not Path(src).exists() or not Path(a2l_in).exists():
            messagebox.showerror('错误', '源文件或A2L输入不存在')
            return
        appstate.save_app_state(addr_src=src, addr_in=a2l_in, addr_out=a2l_out)
        self.app.begin_running()
        threading.Thread(target=self._run, daemon=True,
                         args=(src, a2l_in, a2l_out, self.remove_var.get())).start()

    def _run(self, src, a2l_in, a2l_out, remove_unmatched):
        start = time.time()
        try:
            self.app.clear_log()
            stype = self.src_type_var.get()
            log = self.app.log_msg
            log('=' * 60)
            log('地址映射 - 处理日志')
            log('=' * 60)
            log(f'时间: {timestamp()}')
            log(f'源类型: {stype.upper()} | 源文件: {src}')
            log(f'A2L输入: {a2l_in}')
            log(f'A2L输出: {a2l_out}')
            log(f"删除未匹配: {'是' if remove_unmatched else '否'}")
            log('=' * 60)

            log('\n[1/3] 解析源文件...')
            self.symbols = (parse_elf_symbols(src) if stype == 'elf'
                            else parse_map_symbols(src))
            log(f'  符号数: {len(self.symbols)}')

            log('\n[2/3] 映射地址...')
            total, matched, updated, elf_only, stats = update_a2l_file(
                a2l_in, self.symbols, a2l_out, remove_unmatched)

            log('\n[3/3] 保存完成')
            elapsed = time.time() - start
            rate = f'{matched/total*100:.1f}%' if total > 0 else '0%'
            log(f"\n{'='*60}")
            log('统计汇总')
            log(f"{'='*60}")
            log(f'  变量总数: {total}')
            log(f'  匹配符号: {matched} ({rate})')
            log(f'  地址更新: {updated}')
            log(f"  地址未变: {stats['unchanged']}")
            log(f"  未匹配:   {stats['unmatched']}")
            log(f"  已删除:   {stats['removed_count']}")
            log(f'  ELF独有:  {len(elf_only)}')
            log(f'  处理耗时: {elapsed:.2f}s')
            log(f"{'='*60}")

            log_path = save_log_file(self.app.log_buffer, self.app.log_queue, a2l_out)
            if log_path:
                log(f'\n日志已保存: {log_path}')

            self.app.root.after(0, self.app.status, 'ok', f'完成! 更新 {updated}/{matched}')
            msg = (f'更新完成!\n\n变量总数: {total}\n匹配: {matched}({rate})\n'
                   f'更新: {updated}\n未变: {stats["unchanged"]}\n'
                   f'未匹配: {stats["unmatched"]}\n已删除: {stats["removed_count"]}\n'
                   f'耗时: {elapsed:.2f}s')
            if log_path:
                msg += f'\n\n日志: {log_path}'
            self.app.info('完成', msg)
        except Exception as e:
            self.app.log_msg(f'错误: {e}\n{traceback.format_exc()}')
            self.app.root.after(0, self.app.status, 'err', f'出错: {e}')
            self.app.error('错误', str(e))
        finally:
            self.app.root.after(0, self.app.end_running)
