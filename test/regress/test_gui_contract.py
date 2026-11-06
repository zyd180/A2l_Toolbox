#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GUI 契约与运行态回归 (无真机样本, CI 可跑).

锁定两条已修的 P0:
  1. 在线标定加载必须真正建立运行态 (进度条出现 / 按钮禁用)
  2. gui/calib 死副本不得复活
并按 AGENTS.md 用 root.mainloop() + after 调度, 不用 withdraw+update 轮询.
"""

import os
import time

import _harness  # noqa: F401
import fixtures


def run(suite):
    try:
        import tkinter as tk
    except ImportError:
        suite.check('GUI 测试需要 tkinter', False, '当前解释器无 tkinter')
        return

    # ---- 静态契约: 死代码不得复活 ----
    try:
        import gui.calib  # noqa: F401
        suite.check('gui.calib 死副本已清除', False, '仍可导入')
    except ImportError:
        suite.check('gui.calib 死副本已清除', True)

    from gui.app import App

    tmp = suite.tmpdir()
    a2l, hex_path = fixtures.write_fixture(os.path.join(tmp, 'gui'))

    # 停靠面板状态持久化在用户状态文件里, 跨运行会污染测试:
    # 固定确定性起点 (展开 / 日志页), 与既有用例对 appstate 的使用一致
    import utils.appstate as appstate
    appstate.save_app_state(dock_collapsed=0, dock_tab=1, last_nav=0, last_sub=0)

    root = tk.Tk()
    app = App(root)
    root.update_idletasks()

    suite.check('App 无 _begin_running (旧 hasattr 守卫恒假)',
                not hasattr(app, '_begin_running') and not hasattr(app, '_end_running'))

    # ---- 停靠面板契约 (V2.7.0 工作台化) ----
    panes = [str(p) for p in app.paned.panes()]
    suite.check('停靠面板已加入 PanedWindow', str(app.dock) in panes, str(panes))
    app.show_result('冒烟结果', metrics=[('对象', 8)], warns=['示例警告'])
    suite.eq('结果卡片已入面板', len(app.result_panel.cards), 1)
    suite.check('结果页点亮未读标记', '●' in str(app.dock_nb.tab(0, 'text')),
                str(app.dock_nb.tab(0, 'text')))
    app.select_dock_tab(0)
    root.update_idletasks()
    suite.check('切到结果页清除标记', '●' not in str(app.dock_nb.tab(0, 'text')),
                str(app.dock_nb.tab(0, 'text')))
    app.log_msg('触发未读')
    root.update_idletasks()
    suite.check('日志页点亮未读标记', '●' in str(app.dock_nb.tab(1, 'text')),
                str(app.dock_nb.tab(1, 'text')))
    app._toggle_dock()
    root.update_idletasks()
    panes = [str(p) for p in app.paned.panes()]
    suite.check('折叠后面板移出 PanedWindow', str(app.dock) not in panes, str(panes))
    app._toggle_dock()
    root.update_idletasks()
    panes = [str(p) for p in app.paned.panes()]
    suite.check('再展开回到 PanedWindow', str(app.dock) in panes, str(panes))
    app.clear_log()

    # ---- 页签契约 (V2.7.0: 动作按钮在页签页脚, 全局 action bar 已废除) ----
    suite.check('全局 action bar 已废除', not hasattr(app, 'run_btn')
                and not hasattr(app, 'test_btn'))
    for i, tab in enumerate(app.a2l_tabs):
        app._goto(i)
        root.update_idletasks()
        suite.check('页签%d %s: 页脚开始按钮' % (i + 1, tab.TITLE.strip()),
                    bool(tab.run_btn.winfo_manager()) and
                    tab.run_btn['text'] == tab.RUN_LABEL,
                    'text=%r' % tab.run_btn['text'])
        tb = getattr(tab, 'test_btn', None)
        suite.check('页签%d 测试按钮可见性' % (i + 1),
                    (tb is not None) == tab.HAS_TEST
                    and (tb is None or bool(tb.winfo_manager()) == tab.HAS_TEST))

    # 运行态同步禁用/恢复所有页签页脚按钮
    app.begin_running()
    root.update_idletasks()
    suite.check('运行态: 页脚开始按钮禁用',
                all(str(t.run_btn['state']) == 'disabled' for t in app.a2l_tabs))
    app.end_running()
    root.update_idletasks()
    suite.check('运行态结束: 页脚开始按钮恢复',
                all(str(t.run_btn['state']) == 'normal' for t in app.a2l_tabs))

    app._goto_calib()
    root.update_idletasks()
    suite.check('在线标定为自包含页签 (无页脚动作按钮)',
                not hasattr(app.calib_tab, 'run_btn'))

    # ---- 运行态: 点击加载应立即建立, 结束后恢复 ----
    tab = app.calib_tab
    tab.a2l_var.set(a2l)
    tab.hex_var.set(hex_path)
    t0 = time.time()
    state = {'loaded': False}

    def step_finish():
        suite.check('加载结束: 进度条收起', not app.progress.winfo_manager())
        suite.check('加载结束: load_btn 恢复', str(tab.load_btn['state']) == 'normal')
        suite.check('加载结束: save_btn 解锁', str(tab.save_btn['state']) == 'normal')
        suite.check('加载结束: 数据集按钮解锁',
                    str(tab.dcm_export_btn['state']) == 'normal')
        s = tab.session
        suite.check('session 已建立', s is not None)
        if s is not None:
            suite.eq('session 标定量数', len(s.objects), 5)
            roots = tab.func_tree.get_children('')
            suite.check('分组树已填充', len(roots) > 0, 'roots=%d' % len(roots))
            if roots:
                tab.func_tree.selection_set(roots[0])
                tab.on_tree_select()
                root.update_idletasks()
            suite.check('选中分组后表格有行', len(tab.table.get_children()) > 0,
                        'rows=%d' % len(tab.table.get_children()))

            # ---- 详情页联动 (V2.7.0 阶段3) ----
            suite.eq('停靠面板页数 (结果/日志/详情)', len(app.dock_nb.tabs()), 3)
            items = tab.table.get_children()
            if items:
                # 程序化 selection_set 不触发 <<TreeviewSelect>> (实测),
                # 与产品 _locate_object 同款: 显式推送详情
                tab.table.selection_set(items[0])
                tab._update_detail()
                root.update_idletasks()
                suite.check('详情面板显示选中对象',
                            tab.detail_panel.current_name == items[0],
                            str(tab.detail_panel.current_name))
                # 制造一个修改 (写"当前值+1", 夹具 AX_Cur 首点 raw=0, 写 mid 会踩原值) →
                # 已修改清单出现 → 点击定位回主表格
                obj = tab.session.objects.get(items[0]) or \
                    tab.session.axis_pts.get(items[0])
                if obj is not None and obj.addr:
                    cur = tab.session.read_object(obj)[0]
                    lo = obj.lower if obj.lower is not None else -1e9
                    hi = obj.upper if obj.upper is not None else 1e9
                    new_v = min(max(float(cur) + 1.0, float(lo)), float(hi))
                    if new_v == float(cur):
                        new_v = float(cur) - 1.0
                    tab.session.write_values(obj, [new_v], [0])
                    tab.refresh_all()
                    root.update_idletasks()
                    suite.check('详情面板列出已修改对象',
                                items[0] in tab.detail_panel.dirty_names,
                                str(tab.detail_panel.dirty_names[:3]))
                    tab.detail_panel.locate(items[0])
                    root.update_idletasks()
                    suite.check('点击已修改对象定位到主表格',
                                items[0] in tab.table.selection(), '')
                    tab.session.restore_object(obj)
                    tab.refresh_all()
                    root.update_idletasks()
                    suite.check('还原后已修改清单清空',
                                len(tab.detail_panel.dirty_names) == 0, '')
        state['loaded'] = True
        root.destroy()

    def tick():
        if state['loaded']:
            return
        if (not app.progress.winfo_manager()) and str(tab.load_btn['state']) == 'normal':
            step_finish()
            return
        if time.time() - t0 > 120:
            suite.check('加载在 120s 内结束', False, '超时, 进度条仍在')
            root.destroy()
            return
        root.after(100, tick)

    def start():
        try:
            tab.load_calibration()
            root.update_idletasks()     # 布局需要一次 idle 才会真正 mapped
            # 运行态在调用返回前必须已建立 (旧代码这里全为假)
            suite.check('点击加载后进度条已 pack', bool(app.progress.winfo_manager()),
                        'manager=%r' % app.progress.winfo_manager())
            suite.check('点击加载后进度条已映射', app.progress.winfo_ismapped())
            suite.check('点击加载后 load_btn 禁用',
                        str(tab.load_btn['state']) == 'disabled')
            root.after(100, tick)
        except Exception as e:
            suite.check('加载调用未抛异常', False, repr(e))
            root.destroy()

    root.after(100, start)
    try:
        root.mainloop()
    except Exception as e:
        suite.check('mainloop 正常退出', False, repr(e))

    # ---- 启动加载屏 (main.py 的过渡窗) ----
    from gui.splash import SplashScreen

    root2 = tk.Tk()
    root2.withdraw()
    sp = SplashScreen(root2)
    suite.check('启动屏 无边框', bool(sp.win.overrideredirect()), '')
    suite.check('启动屏 置顶', bool(sp.win.attributes('-topmost')), '')
    sp.show()
    root2.update_idletasks()
    suite.check('启动屏 show 后已映射', bool(sp.win.winfo_ismapped()), '')
    # 几何只有映射之后才有效 (映射前 winfo_geometry 返回 1x1)
    geo = sp.win.geometry()
    expect = '%dx' % int(420 * sp.scale)
    suite.check('启动屏 尺寸按 DPI 缩放', geo.startswith(expect), '%s (期望 %s…)' % (geo, expect))
    suite.check('启动屏 记录了首帧时间', sp.t_first_frame is not None, '')
    sp.step('正在加载图表组件…', 70)
    root2.update_idletasks()
    suite.eq('启动屏 进度条按 70% 填充',
             int(sp.progress.coords(sp._fill)[2]), int(sp._bar_w * 0.7))

    done = {}
    sp.close(on_done=lambda: done.setdefault('t', time.perf_counter()))

    def wait_close():
        if 't' not in done and time.perf_counter() - sp.t_shown < 3.0:
            root2.after(20, wait_close)
            return
        shown_ms = (done.get('t', time.perf_counter()) - sp.t_shown) * 1000.0
        suite.check('启动屏 最短展示 >= 450ms', shown_ms >= 450, '%.0f ms' % shown_ms)
        suite.check('启动屏 close 后已销毁', sp.win is None, '')
        suite.check('启动屏 on_done 已回调', 't' in done, '')
        sp2 = SplashScreen(root2)
        sp2.show()
        sp2.abort()
        suite.check('启动屏 abort 立即销毁', sp2.win is None, '')
        root2.destroy()

    root2.after(20, wait_close)
    try:
        root2.mainloop()
    except Exception as e:
        suite.check('启动屏 mainloop 正常退出', False, repr(e))
