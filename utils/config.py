#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配置模块 - 版本信息和配色方案"""

VERSION = "v2.2.0"

# 配色方案 (现代扁平风格)
COLORS = {
    'bg':           '#eef2f7',   # 窗口背景
    'card':         '#ffffff',   # 卡片/页签内容背景
    'border':       '#d5deea',   # 边框
    'text':         '#1f2937',   # 主文字
    'muted':        '#6b7280',   # 次要文字
    'primary':      '#2563eb',   # 主色
    'primary_dark': '#1d4ed8',   # 主色(深)
    'header':       '#1e3a5f',   # 顶部横幅
    'header_sub':   '#b9c9de',   # 横幅次要文字
    'ok':           '#15803d',
    'ok_bg':        '#e7f5ec',
    'warn':         '#b45309',
    'err':          '#dc2626',
    'err_bg':       '#fdecec',
    'run_bg':       '#e8effc',
    'ready_bg':     '#dbe3ee',
}

# 文件类型配置
FILE_TYPES = {
    'a2l': [("A2L", "*.a2l")],
    'elf': [("ELF", "*.elf")],
    'map': [("MAP", "*.map")],
    'dcm': [("DCM", "*.dcm"), ("All", "*.*")],
    'hex': [("HEX", "*.hex"), ("All", "*.*")],
    'all': [("All", "*.*")],
}
