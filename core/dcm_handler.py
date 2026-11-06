#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DCM 文件解析 + DCM 批量写入 HEX

本模块只做两件事:
  1. parse_dcm   - 解析 KONSERVIERUNG_FORMAT 2.0 的 DCM 数据集 (在线标定与 CLI 共用)
  2. dcm_to_hex  - 批处理入口 (DCM + A2L + HEX -> 新 HEX)

A2L 对象索引与值编码一律复用 core.calib_engine.CalibSession, 本模块不再自建一份:
  - 自建索引会漏掉 FIX_AXIS 隐式轴/限值/GROUP 等 CalibSession 已实现的能力
  - 编码逻辑 (COEFFS 方向/字节序/整数截断) 只允许存在一处, 否则必然分叉
"""

import re
import time
from pathlib import Path


# ==================== DCM 解析 ====================

_DCM_HEAD_RE = re.compile(r'^(FESTWERTEBLOCK|GRUPPENKENNFELD|GRUPPENKENNLINIE|'
                          r'FESTKENNLINIE|FESTWERT|STUETZSTELLENVERTEILUNG)\s+'
                          r'([A-Za-z_]\w*)(.*)$')
_DCM_NUM_RE = re.compile(r'[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?')


def parse_dcm(path, log=None):
    """解析 KONSERVIERUNG_FORMAT 2.0 的 DCM 文件.
    返回 {name: {kind, counts[], xs[], ys[], values[]}};
    KENNFELD 的 values 按行主序 (逐 ST/Y 行) 展平"""
    log = log or (lambda m: None)
    objs = {}
    cur = None
    skip_fkt = 0        # FUNKTIONEN 等无需解析的 0 列块嵌套深度
    with open(path, 'r', encoding='utf-8', errors='surrogateescape') as f:
        for line in f:
            if line[:1] == '*':
                continue    # ETAS 标记/引用行 (如 *SSTX 轴引用), 不影响当前块
            if line[:1] not in ('', ' ', '\t', '\r', '\n'):
                if cur is not None:
                    cur = None
                head = line.strip()
                if head == 'END':
                    if skip_fkt > 0:
                        skip_fkt -= 1
                    continue
                if head.startswith('FUNKTIONEN'):
                    skip_fkt += 1
                    continue
                m = _DCM_HEAD_RE.match(head)
                if m and skip_fkt == 0:
                    counts = [int(x) for x in _DCM_NUM_RE.findall(m.group(3))]
                    cur = {'kind': m.group(1), 'counts': counts,
                           'xs': [], 'ys': [], 'values': []}
                    objs[m.group(2)] = cur
                continue
            if cur is None:
                continue
            s = line.strip()
            if s == 'END':
                cur = None
                continue
            if s.startswith('ST/X'):
                cur['xs'].extend(float(x) for x in _DCM_NUM_RE.findall(s[4:]))
            elif s.startswith('ST/Y'):
                cur['ys'].extend(float(x) for x in _DCM_NUM_RE.findall(s[4:]))
            elif s.startswith('WERT'):
                cur['values'].extend(float(x) for x in _DCM_NUM_RE.findall(s[4:]))
    n_f = sum(1 for o in objs.values() if o['kind'] in ('FESTWERT', 'FESTWERTEBLOCK'))
    n_c = sum(1 for o in objs.values() if o['kind'] in ('GRUPPENKENNLINIE', 'FESTKENNLINIE'))
    n_m = sum(1 for o in objs.values() if o['kind'] == 'GRUPPENKENNFELD')
    n_a = sum(1 for o in objs.values() if o['kind'] == 'STUETZSTELLENVERTEILUNG')
    log('  DCM 对象: 共 %d 个 (标定量/块 %d, 曲线 %d, MAP %d, 轴 %d)' %
        (len(objs), n_f, n_c, n_m, n_a))
    return objs


# ==================== DCM 写入 HEX (批处理) ====================

def dcm_to_hex(dcm_path, a2l_path, hex_path, out_path, log=None):
    """把 DCM 数据集应用到 A2L+HEX 描述的标定区, 输出新 HEX 文件 (不改原文件).

    实现说明: 走 CalibSession (加载 -> 导入 DCM -> 保存), 与 GUI「导入 DCM + 保存 HEX」
    完全同一条代码路径, 因此:
      - 支持 FIX_AXIS 隐式轴 / COM_AXIS 轴值联动 / MAP 存储方向转置
      - 写入受 LOWER/UPPER 限值保护, 超限对象计入 errors 而不写入
      - 输出按 A2L 的 MEMORY_SEGMENT 段定义补 0xFF (对标 INCA 导出)
    返回 {'applied','missing','errors','dirty','out'}"""
    t0 = time.time()
    log = log or (lambda m: None)

    from core.calib_engine import CalibSession

    log('[1/3] 加载 A2L + HEX ...')
    session = CalibSession.load(a2l_path, hex_path, log=log)

    log('[2/3] 导入 DCM 并编码写入 ...')
    res = session.apply_dcm(dcm_path, log=log)
    if res['errors']:
        for name, why in res['errors'][:20]:
            log('  [跳过] %s: %s' % (name, why))
        if len(res['errors']) > 20:
            log('  [跳过] ... 其余 %d 条略' % (len(res['errors']) - 20))
    log('  应用 %d, 未匹配 %d, 错误 %d, 实际改动对象 %d'
        % (res['applied'], res['missing'], len(res['errors']),
           len(session.dirty_objects())))

    log('[3/3] 保存 HEX ...')
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    session.save_hex(out_path)
    log('  输出: %s (耗时 %.1fs)' % (out_path, time.time() - t0))

    return {'applied': res['applied'], 'missing': res['missing'],
            'errors': res['errors'], 'dirty': len(session.dirty_objects()),
            'out': out_path}


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 5:
        print("用法: python dcm_handler.py <dcm_file> <a2l_file> <hex_file> <out_hex>")
        sys.exit(1)

    dcm_path, a2l_path, hex_path, out_path = sys.argv[1:5]
    try:
        r = dcm_to_hex(dcm_path, a2l_path, hex_path, out_path, log=print)
        print("\n写入统计:")
        print("  应用对象: %d" % r['applied'])
        print("  未匹配:   %d" % r['missing'])
        print("  错误:     %d" % len(r['errors']))
        print("  实际改动: %d" % r['dirty'])
    except Exception as e:
        print("错误: %s" % e)
        sys.exit(1)
