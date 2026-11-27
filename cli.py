#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""命令行模式: A2L_Toolbox.exe <子命令> [参数] (不带参数则进 GUI).

从 bat/cmd 调用时附着到调用方控制台打印日志 (AttachConsole), 不弹新黑窗;
exe 是窗口程序, bat 里要用 start /wait 等待结束并获取 %ERRORLEVEL%.
退出码: 0 成功 / 1 执行失败 / 2 参数错误.
"""

import argparse
import os
import sys
import traceback
from pathlib import Path

from utils.config import VERSION


def _attach_console():
    """把 stdout/stderr 接到控制台 (仅窗口模式 exe 且无重定向时需要).

    两种情形都要覆盖: 从 bat/cmd 启动时 exe 可能已继承父控制台
    (AttachConsole 会失败但 CONOUT$ 可直接打开), 也可能没有控制台
    (AttachConsole 附着父进程的控制台). 都没有时日志落工作目录文件.
    """
    if sys.stdout is not None:
        return
    try:
        from ctypes import windll
        windll.kernel32.AttachConsole(0xFFFFFFFF)  # ATTACH_PARENT_PROCESS
        windll.kernel32.SetConsoleOutputCP(65001)
        sys.stdout = open('CONOUT$', 'w', encoding='utf-8',
                          errors='replace', buffering=1)
        sys.stderr = sys.stdout
        return
    except Exception:
        pass
    try:
        sys.stdout = open('A2L_Toolbox_cli.log', 'w', encoding='utf-8',
                          buffering=1)
    except OSError:
        sys.stdout = open(os.devnull, 'w')
    sys.stderr = sys.stdout


def _parse_symbols(src):
    if src.lower().endswith('.map'):
        from core.map_parser import parse_map_symbols
        return parse_map_symbols(src), 'MAP'
    from core.elf_parser import parse_elf_symbols
    return parse_elf_symbols(src), 'ELF'


def _require_files(*paths):
    for p in paths:
        if p and not Path(p).exists():
            raise FileNotFoundError('文件不存在: %s' % p)


def _log_addr_stats(total, matched, updated, stats):
    rate = 100.0 * matched / total if total else 0.0
    print('变量 %d | 匹配 %d (%.1f%%) | 更新 %d | 未变 %d | 未匹配 %d'
          ' | 删除 %d | 保留原地址 %d'
          % (total, matched, rate, updated, stats['unchanged'],
             stats['unmatched'], stats['removed_count'],
             stats['kept_existing']))
    if rate < 50.0:
        print('[警告] 匹配率过低: 符号文件与 A2L 很可能不是同一次构建')


def _cmd_addr(a):
    from core.a2l_parser import update_a2l_file
    _require_files(a.src, a.a2l_in)
    symbols, stype = _parse_symbols(a.src)
    print('[%s] 符号数: %d' % (stype, len(symbols)))
    total, matched, updated, _elf_only, stats = update_a2l_file(
        a.a2l_in, symbols, a.a2l_out, a.remove_unmatched,
        only_missing=a.only_missing)
    _log_addr_stats(total, matched, updated, stats)
    print('输出: %s' % a.a2l_out)
    return 0


def _cmd_merge(a):
    from core.a2l_parser import (extract_a2l_content, write_content_only,
                                 insert_into_header)
    if a.upd_addr and (not a.map or not a.map.lower().endswith('.map')):
        print('错误: --upd-addr 需要 MAP 文件 (--map *.map)')
        return 2
    _require_files(a.folder, a.header, a.map)
    rec, vb, compu, fmap, n, dedup = extract_a2l_content(
        a.folder, not a.no_recursive, map_path=a.map or None, log=print)
    print('文件 %d | 变量块 %d | 同名去重 %d 组 | 结构差异 %d'
          % (n, len(vb), dedup['duplicated'], len(dedup['conflicts'])))
    if a.header:
        insert_into_header(a.header, rec, vb, compu, fmap, a.out, log=print)
    else:
        write_content_only(rec, vb, compu, fmap, a.out)
    if a.upd_addr:
        from core.map_parser import parse_map_symbols
        from core.a2l_parser import update_a2l_file
        symbols = parse_map_symbols(a.map)
        print('[地址] 按 MAP 更新 (%s) ...'
              % ('仅填 0x0000 占位' if a.only_missing else '覆盖已有地址'))
        total, matched, updated, _x, stats = update_a2l_file(
            a.out, symbols, a.out, only_missing=a.only_missing)
        _log_addr_stats(total, matched, updated, stats)
    print('输出: %s' % a.out)
    return 0


def _cmd_sync(a):
    from core.sync_engine import sync_model_a2l
    _require_files(a.base, *a.src)
    if a.addr:
        _require_files(a.addr)
    owner_map = {}
    if a.addr and a.addr.lower().endswith('.map'):
        from core.map_parser import parse_map_ownership
        owner_map = parse_map_ownership(a.addr)
        print('符号归属 MAP: %d 条 (按定义方裁决)' % len(owner_map))
    cur = a.base
    for i, src in enumerate(a.src):
        print('>>> [%d/%d] 同步模型: %s' % (i + 1, len(a.src), Path(src).name))
        sync_model_a2l(src, cur, a.out, purge=not a.no_purge,
                       backup=(not a.no_backup and i == 0), log=print,
                       owner_map=owner_map)
        cur = a.out
    if a.addr:
        from core.a2l_parser import update_a2l_file
        symbols, stype = _parse_symbols(a.addr)
        print('[地址] 按 %s 更新 (%s) ...'
              % (stype, '仅填 0x0000 占位' if a.only_missing else '覆盖已有地址'))
        total, matched, updated, _x, stats = update_a2l_file(
            a.out, symbols, a.out, only_missing=a.only_missing)
        _log_addr_stats(total, matched, updated, stats)
    print('输出: %s' % a.out)
    return 0


def _cmd_dcm(a):
    from core.dcm_handler import dcm_to_hex
    _require_files(a.dcm, a.a2l, a.hex)
    r = dcm_to_hex(a.dcm, a.a2l, a.hex, a.out, log=print)
    print('应用 %d | 未匹配 %d | 错误 %d | 实际改动 %d'
          % (r['applied'], r['missing'], len(r['errors']), r['dirty']))
    print('输出: %s' % r['out'])
    return 1 if r['errors'] else 0


def _build_parser():
    p = argparse.ArgumentParser(
        prog='A2L_Toolbox',
        description='A2L 工具箱命令行模式 (不带参数启动 GUI)')
    p.add_argument('--version', action='version', version=VERSION)
    sub = p.add_subparsers(dest='cmd', required=True)

    pa = sub.add_parser('addr', help='地址映射: 按 ELF/MAP 更新 A2L 变量地址')
    pa.add_argument('--src', required=True, help='ELF/MAP 文件 (按扩展名识别)')
    pa.add_argument('--in', dest='a2l_in', required=True, help='A2L 输入')
    pa.add_argument('--out', dest='a2l_out', required=True, help='A2L 输出')
    pa.add_argument('--remove-unmatched', action='store_true',
                    help='删除符号表中没有的变量')
    pa.add_argument('--only-missing', action='store_true',
                    help='仅填补 0x0000 占位, 不覆盖已有真实地址')

    pm = sub.add_parser('merge', help='合并文件夹中的多个 A2L')
    pm.add_argument('--folder', required=True, help='输入文件夹')
    pm.add_argument('--out', required=True, help='输出 A2L')
    pm.add_argument('--header', help='头文件 A2L (插入 Data 标记处)')
    pm.add_argument('--map', help='符号归属 MAP (同名对象按定义方去重)')
    pm.add_argument('--no-recursive', action='store_true', help='不含子文件夹')
    pm.add_argument('--upd-addr', action='store_true',
                    help='合并后按 --map 更新 ECU 地址')
    pm.add_argument('--only-missing', action='store_true',
                    help='地址更新仅填补 0x0000 占位')

    ps = sub.add_parser('sync', help='模型版本同步: 新版模型 A2L 更新进整车 A2L')
    ps.add_argument('--src', nargs='+', required=True, help='新版模型 A2L (可多个)')
    ps.add_argument('--base', required=True, help='Base A2L (整车 A2L)')
    ps.add_argument('--out', required=True, help='输出 A2L')
    ps.add_argument('--addr', help='同步后按此 ELF/MAP 整体更新地址')
    ps.add_argument('--no-purge', action='store_true',
                    help='不删除旧版有而新版没有的对象')
    ps.add_argument('--no-backup', action='store_true', help='不生成 .bak 备份')
    ps.add_argument('--only-missing', action='store_true',
                    help='地址更新仅填补 0x0000 占位')

    pd = sub.add_parser('dcm', help='DCM 写入 HEX (与 GUI 导入 DCM+保存 HEX 同路径)')
    pd.add_argument('--dcm', required=True, help='DCM 标定文件')
    pd.add_argument('--a2l', required=True, help='A2L 文件')
    pd.add_argument('--hex', required=True, help='HEX 输入')
    pd.add_argument('--out', required=True, help='HEX 输出 (不改原文件)')
    return p


def run(argv=None):
    _attach_console()
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    handlers = {'addr': _cmd_addr, 'merge': _cmd_merge,
                'sync': _cmd_sync, 'dcm': _cmd_dcm}
    try:
        return handlers[args.cmd](args)
    except Exception as e:
        print('错误: %s' % e)
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(run())