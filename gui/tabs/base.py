#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""页签基类: 统一 页签注册 / 任务说明头 / 页脚动作按钮.

V2.7.0 工作台化: 全局 action bar 废除, 开始/测试解析按钮移入页签页脚
(视线动线不再跨区跳跃). 子类通过类属性声明能力:
    TITLE      页签标题
    DESC       顶部任务说明 (空串则不渲染)
    HAS_RUN    是否需要页脚"开始"按钮 (False 则页签自包含, 如在线标定)
    RUN_LABEL  开始按钮文案
    HAS_TEST   是否显示"测试解析"按钮
"""

from tkinter import ttk


class BaseTab(ttk.Frame):

    TITLE = ''
    DESC = ''
    HAS_RUN = True
    RUN_LABEL = '开始'
    HAS_TEST = False

    def __init__(self, notebook, app):
        super().__init__(notebook, style='Card.TFrame', padding=12)
        self.app = app
        # Notebook 挂载 → 注册页签; 普通容器 → 由壳自行 pack (如侧边导航内容栈)
        if isinstance(notebook, ttk.Notebook):
            notebook.add(self, text=self.TITLE)
        if self.DESC:
            ttk.Label(self, text=self.DESC,
                      style='CardMuted.TLabel').pack(anchor='w', pady=(0, 8))
        if self.HAS_RUN:
            self.footer = ttk.Frame(self, style='Card.TFrame')
            self.footer.pack(side='bottom', fill='x', pady=(8, 0))
            self.run_btn = ttk.Button(self.footer, text=self.RUN_LABEL,
                                      style='Primary.TButton', command=self.start)
            self.run_btn.pack(side='left')
            if self.HAS_TEST:
                self.test_btn = ttk.Button(self.footer, text='测试解析',
                                           command=self.test)
                self.test_btn.pack(side='left', padx=(8, 0))
            self.body = ttk.Frame(self, style='Card.TFrame')
            self.body.pack(fill='both', expand=True)
        self.build()

    # ---- 子类接口 ----

    def build(self):
        """构建页签内容. HAS_RUN 页签装入 self.body; 自包含页签装入 self."""

    def start(self):
        """点击页脚开始按钮: 校验输入并开工作线程."""
        raise NotImplementedError

    def test(self):
        """点击测试解析 (仅 HAS_TEST=True 时可达)."""
