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
    DESC = ('将文件夹中的多个 A2L 文件合并为一个: 可指定头文件 A2L 插入 Data 标记处, '
            '或输出去壳纯内容; 同名对象按"定义它的 SWC"保留一份')
    RUN_LABEL = '开始合并'

    def build(self):
        grp = ttk.Labelframe(self.body, text=' 文件选择 ',
                             style='Card.TLabelframe', padding=10)
        grp.pack(fill='x', pady=(0, SPACE['sm']))
        st = appstate.load_app_state()
        self.folder_var = tk.StringVar(value=st.get('merge_folder', ''))
        self.output_var = tk.StringVar(value=st.get('merge_output', ''))
        self.header_var = tk.StringVar(value=st.get('merge_header', ''))
        self.sym_var = tk.StringVar(value=st.get('merge_sym', ''))
        file_row(grp, 0, '输入文件夹:', self.folder_var, self.browse_folder, col=0)
        file_row(grp, 0, '输出文件:', self.output_var, self.browse_output, col=1)
        file_row(grp, 1, '头文件A2L:', self.header_var, self.browse_header,
                 hint='(可选) 合并内容插入此文件的 Data 区域', col=0)
        file_row(grp, 1, '符号归属MAP:', self.sym_var, self.browse_sym,
                 hint='(可选) 按 MAP 中符号的定义模块判定同名对象归属; '
                      '不提供则按名称前缀/限值启发式裁决', col=1)

        opt = ttk.Frame(self.body, style='Card.TFrame')
        opt.pack(fill='x')
        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text='包含子文件夹', variable=self.recursive_var,
                        style='Card.TCheckbutton').pack(side='left', padx=SPACE['xs'])
        self.upd_addr_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text='合并后更新 ECU 地址 (只填 0x0000 占位, 用上面的 MAP)',
                        variable=self.upd_addr_var,
                        style='Card.TCheckbutton').pack(side='left', padx=SPACE['xl'])

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

    def browse_sym(self):
        p = filedialog.askopenfilename(title='选择符号归属文件 (MAP)',
                                       filetypes=FILE_TYPES['map'] + FILE_TYPES['all'])
        if p:
            self.sym_var.set(p)

    # ---------- 运行 ----------
    def start(self):
        folder = self.folder_var.get().strip()
        output = self.output_var.get().strip()
        header = self.header_var.get().strip()
        sym = self.sym_var.get().strip()
        if not folder or not output:
            messagebox.showerror('错误', '请填写输入文件夹和输出文件')
            return
        if not Path(folder).exists():
            messagebox.showerror('错误', '文件夹不存在')
            return
        if header and not Path(header).exists():
            messagebox.showerror('错误', '头文件A2L不存在')
            return
        if sym and not Path(sym).exists():
            messagebox.showerror('错误', f'符号归属文件不存在: {sym}')
            return
        upd_addr = self.upd_addr_var.get()
        if upd_addr and not sym:
            messagebox.showerror('错误', '已勾选"合并后更新 ECU 地址", 请先选择符号归属MAP')
            return
        if upd_addr and not sym.lower().endswith('.map'):
            messagebox.showerror('错误', '更新地址需要 MAP 文件 (.map); ELF 不含定义模块信息')
            return
        appstate.save_app_state(merge_folder=folder, merge_output=output,
                                merge_header=header, merge_sym=sym)
        self.app.begin_running()
        threading.Thread(target=self._run, daemon=True,
                         args=(folder, output, header, self.recursive_var.get(),
                               sym, upd_addr)).start()

    def _run(self, folder, output, header, recursive, sym='', upd_addr=False):
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
            log(f'符号归属MAP: {sym if sym else "(无, 用名称前缀/限值启发式)"}')
            log(f"包含子文件夹: {'是' if recursive else '否'}")
            log('=' * 60)

            log('\n[1/3] 扫描并提取 A2L 内容...')
            (record_lines, variable_blocks, compu_lines, file_var_map,
             file_count, dedup) = extract_a2l_content(
                folder, recursive, map_path=sym or None, log=log)

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
                                   compu_lines, file_var_map, output, log=log)
                log('  模式: 插入了文件')
            else:
                write_content_only(record_lines, variable_blocks,
                                   compu_lines, file_var_map, output)
                log('  模式: 纯内容输出 (去壳)')

            report = ''
            if dedup['conflicts']:
                report = self._write_dedup_report(output, dedup)
                log('  结构差异清单: %s' % report)

            # 可选: 用同一个 MAP 把合并产物里的 0x0000 占位地址刷成真实地址
            addr_info = ''
            addr_stats = None
            if upd_addr:
                log('\n[地址] 按 MAP 更新 ECU 地址 ...')
                from core.map_parser import parse_map_symbols
                from core.a2l_parser import update_a2l_file
                symbols = parse_map_symbols(sym)
                log('  符号数: %d' % len(symbols))
                total, matched, updated, _only, astats = update_a2l_file(
                    output, symbols, output, only_missing=True)
                rate = (100.0 * matched / total) if total else 0.0
                log('  变量 %d | 匹配 %d (%.1f%%) | 地址更新 %d | 未匹配 %d'
                    % (total, matched, rate, updated, astats['unmatched']))
                if rate < 50.0:
                    log('  [警告] 匹配率过低: 该 MAP 与这批 A2L 很可能不是同一次构建')
                addr_info = ('\n\n地址更新: 变量 %d, 匹配 %d (%.1f%%), 更新 %d, 未匹配 %d'
                             % (total, matched, rate, updated, astats['unmatched']))
                addr_stats = (total, matched, rate, updated, astats['unmatched'])

            elapsed = time.time() - start
            log('\n[3/3] 完成')
            log(f"\n{'='*60}")
            log('合并统计')
            log(f"{'='*60}")
            log(f'  源文件数:     {file_count}')
            log(f'  变量块总数:   {total_vars}')
            log(f'  同名去重:     {dedup["duplicated"]} 组 '
                f'(MAP {dedup["by_map"]} / 前缀 {dedup["by_prefix"]} / '
                f'等价 {dedup["by_equal"]} / 限值 {dedup["by_limit"]})')
            log(f'  结构差异待复核: {len(dedup["conflicts"])}')
            if addr_stats:
                log(f'  地址更新: 匹配 {addr_stats[1]}/{addr_stats[0]}'
                    f' ({addr_stats[2]:.1f}%), 更新 {addr_stats[3]},'
                    f' 未匹配 {addr_stats[4]}')
            log(f'  RECORD_LAYOUT: {len(record_lines)}')
            log(f'  COMPU_METHOD:  {len(compu_lines)}')
            log(f'  处理耗时:     {elapsed:.2f}s')
            log(f"{'='*60}")

            mode_str = '插入头文件' if header else '纯内容'
            self.app.root.after(0, self.app.status, 'ok',
                                f'完成! {file_count}文件, {total_vars}变量 [{mode_str}]')
            # 完成反馈: 结果卡片常驻右停靠面板 (不再弹 messagebox)
            warns = []
            if dedup['conflicts']:
                warns.append('%d 个对象存在结构差异(典型为限值不同), 已按规则裁决, '
                             '清单: %s' % (len(dedup['conflicts']), report))
            if (sym and dedup['duplicated'] and dedup['map_symbol_hits']
                    and dedup['by_map'] * 2 < dedup['duplicated']):
                warns.append('MAP 只能定位 %d/%d 组, 该 MAP 很可能与这批 A2L 不是'
                             '同一次构建, 建议使用同版本 MAP'
                             % (dedup['by_map'], dedup['duplicated']))
            paths = [str(output)] + ([report] if dedup['conflicts'] else [])
            metrics = [('源文件', file_count), ('变量块', total_vars),
                       ('同名去重', '%d 组' % dedup['duplicated']),
                       ('MAP定位', dedup['by_map']),
                       ('前缀', dedup['by_prefix']),
                       ('等价', dedup['by_equal']),
                       ('限值兜底', dedup['by_limit'])]
            if addr_stats:
                metrics.append(('地址更新', '%d/%d (%.1f%%)'
                                % (addr_stats[3], addr_stats[1], addr_stats[2])))
            self.app.root.after(0, lambda: self.app.show_result(
                '合并完成 [%s]' % mode_str,
                metrics=metrics,
                paths=paths, warns=warns, ts=timestamp()))
        except Exception as e:
            self.app.log_msg(f'错误: {e}\n{traceback.format_exc()}')
            self.app.root.after(0, self.app.status, 'err', f'出错: {e}')
            self.app.error('错误', str(e))
        finally:
            self.app.root.after(0, self.app.end_running)

    @staticmethod
    def _write_dedup_report(output, dedup):
        """把结构差异(需复核)对象写成清单, 返回文件路径"""
        p = Path(str(output) + '_dedup.txt')
        try:
            with open(p, 'w', encoding='utf-8') as f:
                f.write('同名对象去重 - 结构差异清单\n')
                f.write('=' * 78 + '\n')
                f.write('说明: 同一对象被多个模型 A2L 声明且内容不一致, 已按下列规则裁决。\n'
                        '      保留"定义方"那份时, 其限值可能与引用方不同 (定义方常为 255 的\n'
                        '      uint8 兜底, 引用方可能已收紧到真实枚举范围), 请按需复核。\n\n')
                for c in dedup['conflicts']:
                    f.write('[%s] %s -> 保留 %s (依据: %s)\n'
                            % (c['type'], c['name'], c['chosen'], c['reason']))
                    for fn, model, lo, hi, same in c['candidates']:
                        if fn == c['chosen']:
                            tag = '  <== 保留'
                        elif same:
                            tag = '   (等价: 仅 CM 名/长标识/数字写法不同)'
                        else:
                            tag = ''
                        f.write('    %-28s model=%-28s 限值 %s .. %s%s\n'
                                % (fn, model,
                                   '-' if lo is None else lo,
                                   '-' if hi is None else hi, tag))
                    f.write('\n')
            return str(p)
        except OSError as e:
            return '(清单写入失败: %s)' % e
