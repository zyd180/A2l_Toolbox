#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GUI 通用件回归: CellGrid 虚拟化 + LogDock 结构化日志.

CellGrid 在 V2.7.0 从"每格 Frame+Label 子窗口"重写为 Canvas 单层绘制,
本文件锁定其公共行为 (选择/复制/粘贴/编辑提交/表头编辑/命中测试),
防止后续编辑器改动或再次重构时悄悄破坏 API 语义。

编辑提交通过 _commit_editor() 方法调用触发 (不需要真实键盘事件焦点),
符合 AGENTS.md 对 GUI 回归的约束 (不用 withdraw+update 轮询).
"""

import os

import _harness  # noqa: F401
from gui.tabs.calib.widgets import CellGrid, ramp_color, parse_tsv


def run(suite):
    try:
        import tkinter as tk
    except ImportError:
        suite.check('GUI 测试需要 tkinter', False, '当前解释器无 tkinter')
        return

    # ---- 纯函数 ----
    suite.eq('ramp_color 0 为绿', ramp_color(0.0), '#009040')
    suite.eq('ramp_color 1 为红', ramp_color(1.0), '#dc3c28')
    suite.eq('ramp_color 中点为黄', ramp_color(0.5), '#ffeb78')
    suite.check('ramp_color NaN 归 0', ramp_color(float('nan')).startswith('#'), '')
    suite.eq('parse_tsv 两行两列', parse_tsv('a\tb\nc\td'),
             [['a', 'b'], ['c', 'd']])

    root = tk.Tk()
    root.withdraw()
    try:
        # ---- 基本数据 ----
        g = CellGrid(root, readonly=False)
        g.set_data([['1', '2'], ['3', '4'], ['5', '6']],
                   colors=[[0.0, 0.5], [None, 1.0], [None, None]],
                   row_headers=['r0', 'r1', 'r2'], col_headers=['c0', 'c1'])
        suite.eq('n_rows', g.n_rows, 3)
        suite.eq('n_cols', g.n_cols, 2)
        suite.eq('values 保持', g.values[1], ['3', '4'])

        # ---- 命中测试 (虚拟化核心: 坐标 -> 逻辑格) ----
        suite.eq('命中 (0,0)', g._hit(CellGrid.CELL_W + 5, CellGrid.CELL_H + 5),
                 ('cell', 0, 0))
        suite.eq('命中 (2,1)', g._hit(CellGrid.CELL_W * 2 + 5, CellGrid.CELL_H * 3 + 5),
                 ('cell', 2, 1))
        suite.eq('命中列头', g._hit(CellGrid.CELL_W * 2 + 5, CellGrid.CELL_H - 5),
                 ('col', 1))
        suite.eq('命中行头', g._hit(5, CellGrid.CELL_H * 2 + 5), ('row', 1))
        suite.eq('命中角头', g._hit(5, 5), ('corner',))
        suite.check('越界不命中', g._hit(5000, 5000) is None, str(g._hit(5000, 5000)))

        # ---- 顶部说明条存在时行头/单元格命中整体下移一个 CELL_H ----
        g.set_data([['a', 'b']], row_headers=['x'], col_headers=['u', 'v'],
                   top_band='X轴: demo')
        suite.eq('带 top_band 命中 (0,0)',
                 g._hit(CellGrid.CELL_W + 5, CellGrid.CELL_H * 2 + 5), ('cell', 0, 0))
        suite.eq('带 top_band 命中列头',
                 g._hit(CellGrid.CELL_W + 5, CellGrid.CELL_H + 5), ('col', 0))

        # ---- 选择 / 复制 / 粘贴 ----
        g.set_data([['1', '2', '3'], ['4', '5', '6']],
                   row_headers=['r0', 'r1'], col_headers=['c0', 'c1', 'c2'])
        g._select(0, 1)
        suite.eq('单格选区', g.selection_rect(), (0, 0, 1, 1))
        g._select(1, 2, extend=True)
        suite.eq('扩展选区', g.selection_rect(), (0, 1, 1, 2))
        suite.eq('复制为 TSV', g.copy_selection(), '2\t3\n5\t6')

        root.clipboard_clear()
        root.clipboard_append('9\t8')
        g._select(0, 0)     # 粘贴从焦点格起
        edits = g.paste_from_clipboard()
        suite.eq('粘贴从焦点格起', edits, {(0, 0): '9', (0, 1): '8'})
        # 越界部分被丢弃 (粘贴 2 列到只剩 1 列的行尾)
        g._select(0, 2)
        suite.eq('粘贴越界部分丢弃', g.paste_from_clipboard(), {(0, 2): '9'})

        # ---- 编辑提交 (on_edit 回调) ----
        got = []
        g2 = CellGrid(root, readonly=False, on_edit=lambda r, c, t: got.append((r, c, t)))
        g2.set_data([['10', '20']])
        g2._edit_at(0, 0)
        suite.check('编辑器已打开', g2._entry is not None, '')
        g2._entry.delete(0, 'end')
        g2._entry.insert(0, '99')
        g2._commit_editor()
        suite.eq('提交触发 on_edit', got, [(0, 0, '99')])
        suite.check('提交后编辑器关闭', g2._entry is None, '')

        # 取消 (Escape 路径): on_edit 不触发; values 只由调用方经 reload 更新 (与旧版一致)
        g2._edit_at(0, 0)
        g2._cancel_editor()
        suite.eq('取消不触发 on_edit', got, [(0, 0, '99')])
        suite.eq('取消后 values 不变 (CellGrid 不代写)', g2.values[0][0], '10')

        # ---- 表头编辑 ----
        hdr = []
        g3 = CellGrid(root, readonly=False, editable_headers=True,
                      on_edit_header=lambda k, i, t: hdr.append((k, i, t)))
        g3.set_data([['1', '2']], row_headers=['7'], col_headers=['8'])
        g3._edit_header('col', 0)
        g3._entry.delete(0, 'end')
        g3._entry.insert(0, '8.5')
        g3._commit_editor()
        suite.eq('列头编辑回调', hdr, [('col', 0, '8.5')])
        g3._edit_header('row', 0)
        g3._entry.delete(0, 'end')
        g3._entry.insert(0, '7.5')
        g3._commit_editor()
        suite.eq('行头编辑回调', hdr, [('col', 0, '8.5'), ('row', 0, '7.5')])

        # readonly: 编辑入口全部关闭
        g4 = CellGrid(root, readonly=True)
        g4.set_data([['1']])
        g4._edit_at(0, 0)
        suite.check('readonly 不开编辑器', g4._entry is None, '')

        # refresh_value 更新值与画布文字
        g5 = CellGrid(root)
        g5.set_data([['1', '2']])
        g5.refresh_value(0, 1, '42', color=0.3)
        suite.eq('refresh_value 更新 values', g5.values[0][1], '42')
        suite.eq('refresh_value 更新 colors', g5.colors[0][1], 0.3)
        canvas_text = g5.canvas.itemcget(g5._text[(0, 1)], 'text')
        suite.eq('refresh_value 更新画布文字', canvas_text, '42')

        # 超长文本截断显示但 values 保留原文 (复制粘贴不失真)
        long_val = '12345678901234567890'
        g6 = CellGrid(root)
        g6.set_data([[long_val]])
        shown = g6.canvas.itemcget(g6._text[(0, 0)], 'text')
        suite.check('长文本画布端截断', len(shown) < len(long_val), shown)
        suite.eq('长文本 values 端保留原文', g6.values[0][0], long_val)
        g6._select(0, 0)    # copy 依赖选区 (无焦点返回空串, 旧契约)
        suite.check('复制取的是原文', long_val in g6.copy_selection(), '')

        # ---- LogDock 结构化级别 ----
        from gui.common.logdock import LogDock
        dock = LogDock(root)
        dock.log_msg(('err', '结构化错误'))
        dock.log_msg('普通文本警告', level='warn')
        dock.log_msg('普通文本 (关键词猜色: 完成)')
        suite.eq('元组写入 buffer 取纯文本', dock.buffer, ['结构化错误', '普通文本警告',
                                                 '普通文本 (关键词猜色: 完成)'])
        tags_err = dock.text.tag_names('1.5')       # 第 1 行 = 结构化错误
        suite.check('元组 err 着色生效', 'err' in tags_err, str(tags_err))
        tags_ok = dock.text.tag_names('3.5')        # 第 3 行 = 关键词猜色
        suite.check('关键词猜色兜底仍生效', 'ok' in tags_ok, str(tags_ok))

        # save_log_file 兼容含元组的队列 (旧回归点: 写文件绝不能出现元组 repr)
        from utils.logger import save_log_file
        out_log = os.path.join(suite.tmpdir(), 'log.txt')
        path = save_log_file(['已渲染行'], [('排队元组', 'ok'), '排队纯文本'], out_log)
        suite.check('save_log_file 返回路径', bool(path), str(path))
        if path:
            content = open(path, encoding='utf-8').read()
            suite.check('队列元组被还原为纯文本', '排队元组' in content, content[:200])
            suite.check('文件中无元组 repr', "('排队元组'" not in content, '')
            suite.check('已渲染行在文件中', '已渲染行' in content, '')
    finally:
        root.destroy()
