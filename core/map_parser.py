#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MAP 文件解析模块 - 提取变量符号地址"""

import re

# 各编译器 MAP 格式的符号行模式, 按优先级排列.
# 每项: (正则, 地址捕获组号, 名字捕获组号)
_MAP_PATTERNS = [
    # Green Hills / TI 多列符号表:
    #   0x804084dd 0x804084dd     1 g Brake_bBrkPedlPsd_E  <段/目标文件信息...>
    # 第1个地址为符号地址, 第2个为结束地址 (可省略), 之后是十进制大小与绑定字母
    (re.compile(r'^(0[xX][0-9A-Fa-f]+)(?:\s+0[xX][0-9A-Fa-f]+)?\s+\d+\s+\S+\s+([A-Za-z_]\w*)',
                re.MULTILINE), 1, 2),
    # GNU ld 链接脚本赋值: 符号名 = 0x地址
    (re.compile(r'^([A-Za-z_][\w.]*)\s*=\s*(0[xX][0-9A-Fa-f]+)', re.MULTILINE), 2, 1),
    # GNU ld 符号续行 (缩进的 地址 + 名字):
    #   "                0x00000800                AwdIn_InterFace_Action1"
    (re.compile(r'^[ \t]+(0[xX][0-9A-Fa-f]+)[ \t]+([A-Za-z_]\w*)[ \t]*$', re.MULTILINE), 1, 2),
    # IAR: 符号名 0x地址
    (re.compile(r'^([A-Za-z_]\w*)[ \t]+(0[xX][0-9A-Fa-f]+)[ \t]*$', re.MULTILINE), 2, 1),
]

# 伪符号名: 形如十六进制地址或纯数字 (旧版误把地址列当名字的典型产物)
_PSEUDO_NAME_RE = re.compile(r'(?:0[xX][0-9A-Fa-f]+|\d+)')


def _collect(content):
    """按优先级尝试各格式, 返回第一个解析出有效符号的模式结果"""
    for pat, g_addr, g_name in _MAP_PATTERNS:
        symbols = {}
        for m in pat.finditer(content):
            name = m.group(g_name)
            if _PSEUDO_NAME_RE.fullmatch(name):
                continue    # 名字形似地址, 视为误匹配跳过
            try:
                addr = int(m.group(g_addr), 16)
            except ValueError:
                continue
            if addr > 0:
                symbols[name] = addr
        if symbols:
            return symbols
    return {}


def parse_map_symbols(map_path):
    """解析 MAP 文件，提取变量符号地址"""
    with open(map_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    symbols = _collect(content)

    # 兜底: MSVC 格式 "0001:00001000  symbol_name" (段:偏移)
    if not symbols:
        seg_pattern = re.compile(r'^([0-9A-Fa-f]{4}):([0-9A-Fa-f]{8})\s+([A-Za-z_]\w*)',
                                 re.MULTILINE)
        for m in seg_pattern.finditer(content):
            try:
                addr = int(m.group(1), 16) * 0x10000 + int(m.group(2), 16)
            except ValueError:
                continue
            if addr > 0:
                symbols[m.group(3)] = addr

    return symbols


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python map_parser.py <map_file>")
        sys.exit(1)

    try:
        symbols = parse_map_symbols(sys.argv[1])
        print(f"符号数: {len(symbols)}")
        for name, addr in list(symbols.items())[:20]:
            print(f"  {name:40s} 0x{addr:08X}")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)
