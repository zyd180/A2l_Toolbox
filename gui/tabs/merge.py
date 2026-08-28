#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""合并A2L页签: 多个 A2L 合并为一, 可选头文件插入或去壳纯内容."""

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
from core.a2l_parser import (
    extract_a2l_content,
    write_content_only,
    insert_into_header,
)


class MergeTab(BaseTab):

    TITLE = '  合并A2L  '
    DESC = '将文件夹中的多个 A2L 文件合并为一个: 可指定头文件 A2L 插入 Data 标记处, 或输出去壳纯内容'
    RUN_LABEL = '开始合并'

    def build(self):
        grp = ttk.Labelframe(self.body, text=' 文件选择 ',
                             style='Card.TLabelframe', padding=10)
        grp.pack(fill='x', pady=(0, SPACE['sm']))
        st = appstate.load_app_state()
        self.folder_var = tk.StringVar(value=st.get('merge_folder', ''))
        self.output_var = tk.StringVar(value=st.get('merge_output', ''))
        self.header_var = tk.StringVar(value=st.get('merge_header', ''))
        file_row(grp, 0, '输入文件夹:', self.folder_var, self.browse_folder)
        file_row(grp, 1, '输出文件:', self.output_var, self.browse_output)
        file_row(grp, 2, '头文件A2L:', self.header_var, self.browse_header,
                 hint='(可选) 选择后将合并内容插入此文件的 Data 区域')

        opt = ttk.Frame(self.body, style='Card.TFrame')
        opt.pack(fill='x')
        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text='包含子文件夹', variable=self.recursive_var,
                        style='Card.TCheckbutton').pack(side='left', padx=SPACE['xs'])

    # ---------- 浏览 ----------
    def browse_folder(self):
        p = filedialog.askdirectory(title='选择包含A2L文件的文件夹')
        if p:
            self.folder_var.set(p)
            if not self.output_var.get():
                self.output_var.set(str(Path(p) / 'merged.a2l'))

    def browse_output(self):
        p = filedialog.asksaveasfilename(title='保存合并后的A2L', defaultextension='.a2l')
        if p:
            self.output_var.set(p)

    def browse_header(self):
        p = filedialog.askopenfilename(title='选择头文件A2L', filetypes=FILE_TYPES['a2l'])
        if p:
            self.header_var.set(p)

    # ---------- 运行 ----------
    def start(self):
        folder = self.folder_var.get().strip()
        output = self.output_var.get().strip()
        header = self.header_var.get().strip()
        if not folder or not output:
            messagebox.showerror('错误', '请填写输入文件夹和输出文件')
            return
        if not Path(folder).exists():
            messagebox.showerror('错误', '文件夹不存在')
            return
        if header and not Path(header).exists():
            messagebox.showerror('错误', '头文件A2L不存在')
            return
        appstate.save_app_state(merge_folder=folder, merge_output=output,
                                merge_header=header)
        self.app.begin_running()
        threading.Thread(target=self._run, daemon=True,
                         args=(folder, output, header, self.recursive_var.get())).start()

    def _run(self, folder, output, header, recursive):
        start = time.time()
        try:
            self.app.clear_log()
            log = self.app.log_msg
            log('=' * 60)
            log('合并 A2L - 处理日志')
            log('=' * 60)
            log(f'时间: {timestamp()}')
            log(f'输入文件夹: {folder}')
            log(f'输出文件: {output}')
            log(f'头文件A2L: {header if header else "(无, 输出纯内容)"}')
            log(f"包含子文件夹: {'是' if recursive else '否'}")
            log('=' * 60)

            log('\n[1/3] 扫描并提取 A2L 内容...')
            record_lines, variable_blocks, compu_lines, file_var_map, file_count = \
                extract_a2l_content(folder, recursive)

            total_vars = len(variable_blocks)
            log(f'  文件数: {file_count}')
            log(f'  变量块: {total_vars}')
            log(f'  RECORD_LAYOUT: {len(record_lines)}')
            log(f'  COMPU_METHOD: {len(compu_lines)}')
            log('  有变量的文件: '
                f'{len([k for k, v in file_var_map.items() if any(v[x] for x in v)])}')

            log('\n[2/3] 写入内容...')
            if header:
                insert_into_header(header, record_lines, variable_blocks,
                                   compu_lines, file_var_map, output)
                log('  模式: 插入了文件')
            else:
                write_content_only(record_lines, variable_blocks,
                                   compu_lines, file_var_map, output)
                log('  模式: 纯内容输出 (去壳)')

            elapsed = time.time() - start
            log('\n[3/3] 完成')
            log(f"\n{'='*60}")
            log('合并统计')
            log(f"{'='*60}")
            log(f'  源文件数:     {file_count}')
            log(f'  变量块总数:   {total_vars}')
            log(f'  RECORD_LAYOUT: {len(record_lines)}')
            log(f'  COMPU_METHOD:  {len(compu_lines)}')
            log(f'  处理耗时:     {elapsed:.2f}s')
            log(f"{'='*60}")

            mode_str = '插入头文件' if header else '纯内容'
            self.app.root.after(0, self.app.status, 'ok',
                                f'完成! {file_count}文件, {total_vars}变量 [{mode_str}]')
            self.app.info('完成',
                          f'合并完成!\n\n源文件: {file_count}\n变量块: {total_vars}\n'
                          f'模式: {mode_str}\n耗时: {elapsed:.2f}s\n\n输出: {output}')
        except Exception as e:
            self.app.log_msg(f'错误: {e}\n{traceback.format_exc()}')
            self.app.root.after(0, self.app.status, 'err', f'出错: {e}')
            self.app.error('错误', str(e))
        finally:
            self.app.root.after(0, self.app.end_running)
