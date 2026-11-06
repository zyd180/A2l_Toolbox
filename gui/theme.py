#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""设计令牌 + ttk 样式工厂.

所有视觉参数集中于此: 色板 / 间距(8px网格) / 字号阶梯 / 语义状态色.
页签代码只允许引用本模块的 TOKEN, 不再散落硬编码样式.
"""

import tkinter as tk
from tkinter import ttk

from utils.config import COLORS as _COLORS

# ---------- 色板 (沿用既有视觉, 补齐语义梯度) ----------
COLORS = dict(_COLORS)
COLORS.update({
    'tab_idle':   '#dbe3ee',     # 未选中页签底
    'nav_hover':  '#24406b',
    'nav_sub_on': '#dbe7ff',
    'log_bg':     '#fbfcfe',
    'log_fg':     '#24313f',
    'log_dim':    '#8a94a3',
    'link':       '#8ab4f8',
    'btn_disabled_bg': '#9db8e8',
    'btn_disabled_fg': '#eaf1fb',
})

# ---------- 间距 (8px 网格) ----------
SPACE = {
    'xs': 4,
    'sm': 8,
    'md': 12,
    'lg': 16,
    'xl': 24,
}

# ---------- 圆角 / 分割线 / 悬停 (工作台化布局的补齐 token) ----------
# Tk 原生不画圆角, 这些 token 目前用于自绘控件 (导航条/结果卡片/网格),
# 先集中定义, 阶段1 起自绘组件一律从这里取值.
RADIUS = {
    'sm': 3,
    'md': 6,
    'lg': 10,
}

DIVIDER = COLORS['border']          # 面板分割线
HOVER_BG = COLORS['tab_idle']       # 通用悬停底色
SELECT_BG = COLORS['primary']       # 选中态底色
SELECT_FG = '#ffffff'               # 选中态文字

# 密度档: compact 用于右停靠面板/表格行, comfortable 用于表单
# (在 FONT 定义之后填充, 见文件下方 DENSITY.update)
DENSITY = {}
DENSITY_DEFAULT = 'comfortable'

# ---------- 字号阶梯 ----------
FONT_FAMILY = '微软雅黑'
FONT_LOG = 'Consolas'
FONT = {
    'body':   (FONT_FAMILY, 9),
    'bold':   (FONT_FAMILY, 9, 'bold'),
    'title':  (FONT_FAMILY, 16, 'bold'),
    'log':    (FONT_LOG, 9),
    'log_b':  (FONT_LOG, 9, 'bold'),
}

# 密度档具体值 (FONT 已定义): compact 用于右停靠面板/表格行, comfortable 用于表单
DENSITY.update({
    'compact':     {'row': 22, 'pad_v': 2, 'pad_h': 6, 'font': FONT['body']},
    'comfortable': {'row': 26, 'pad_v': 4, 'pad_h': 8, 'font': FONT['body']},
})

# ---------- 状态栏语义色 ----------
STATUS_STYLES = {
    'ready':   (COLORS['ready_bg'], '#374151'),
    'running': (COLORS['run_bg'],   COLORS['primary_dark']),
    'ok':      (COLORS['ok_bg'],    COLORS['ok']),
    'err':     (COLORS['err_bg'],   COLORS['err']),
}


def setup_style(root):
    """注册全部 ttk 样式 (clam 基底). 返回 style 实例."""
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass

    C = COLORS
    style.configure('.', font=FONT['body'], background=C['bg'], foreground=C['text'])
    style.configure('TFrame', background=C['bg'])
    style.configure('Card.TFrame', background=C['card'])
    style.configure('TLabel', background=C['bg'])
    style.configure('Card.TLabel', background=C['card'])
    style.configure('CardMuted.TLabel', background=C['card'], foreground=C['muted'])
    style.configure('HeaderTitle.TLabel', background=C['header'],
                    foreground='white', font=FONT['title'])
    style.configure('HeaderSub.TLabel', background=C['header'],
                    foreground=C['header_sub'], font=FONT['body'])
    style.configure('HeaderLink.TLabel', background=C['header'],
                    foreground=C['link'], font=FONT['body'], cursor='hand2')

    style.configure('TButton', background=C['card'], foreground=C['text'],
                    padding=(12, 5), font=FONT['body'])
    style.map('TButton', background=[('active', C['tab_idle']),
                                     ('disabled', C['tab_idle'])],
              foreground=[('disabled', C['muted'])])
    style.configure('Primary.TButton', background=C['primary'], foreground='white',
                    borderwidth=0, focusthickness=0, padding=(20, 7),
                    font=FONT['bold'])
    style.map('Primary.TButton',
              background=[('active', C['primary_dark']),
                          ('disabled', C['btn_disabled_bg'])],
              foreground=[('disabled', C['btn_disabled_fg'])])
    style.configure('Tool.TButton', padding=(9, 4))

    style.configure('TEntry', padding=(6, 5), fieldbackground=C['card'],
                    bordercolor=C['border'])
    style.configure('Card.TRadiobutton', background=C['card'])
    style.configure('Card.TCheckbutton', background=C['card'])
    style.map('Card.TRadiobutton', background=[('active', C['card'])])
    style.map('Card.TCheckbutton', background=[('active', C['card'])])

    style.configure('Card.TLabelframe', background=C['card'],
                    bordercolor=C['border'], relief='solid', borderwidth=1)
    style.configure('Card.TLabelframe.Label', background=C['card'],
                    foreground=C['primary_dark'], font=FONT['bold'])

    style.configure('TNotebook', background=C['card'], borderwidth=0)
    style.configure('TNotebook.Tab', padding=(18, 7), background=C['tab_idle'],
                    font=FONT['body'])
    style.map('TNotebook.Tab',
              background=[('selected', C['card'])],
              foreground=[('selected', C['primary_dark'])],
              font=[('selected', FONT['bold'])],
               expand=[('selected', (0, 0, 0, 2))])

    style.configure('Treeview', background=C['card'], fieldbackground=C['card'],
                    foreground=C['text'], rowheight=24, font=FONT['body'])
    style.map('Treeview', background=[('selected', C['primary'])],
              foreground=[('selected', 'white')])
    style.configure('Treeview.Heading', background=C['tab_idle'],
                    foreground=C['primary_dark'], font=FONT['bold'], padding=(6, 5))
    style.map('Treeview.Heading', background=[('active', C['border'])])

    style.configure('Vertical.TScrollbar', troughcolor=C['bg'],
                    background=C['border'], arrowcolor=C['muted'], borderwidth=0)
    style.configure('Horizontal.TScrollbar', troughcolor=C['bg'],
                    background=C['border'], arrowcolor=C['muted'], borderwidth=0)

    style.configure('Accent.Horizontal.TProgressbar', troughcolor=C['tab_idle'],
                    background=C['primary'], borderwidth=0, thickness=6)
    return style
