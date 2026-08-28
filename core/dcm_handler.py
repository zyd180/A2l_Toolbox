#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DCM 文件解析模块 - 解析 KONSERVIERUNG_FORMAT 格式的标定数据"""

import re
import time
from collections import Counter
from pathlib import Path

from .hex_handler import load_intel_hex, save_intel_hex, encode_raw
from .sync_engine import _read_lines, _parse_blocks, _get_addr


# ==================== 常量定义 ====================

_DCM_OBJ_KINDS = ('FESTWERT', 'FESTWERTEBLOCK', 'GRUPPENKENNLINIE',
                  'GRUPPENKENNFELD', 'FESTKENNLINIE', 'STUETZSTELLENVERTEILUNG')

# A2L 数据类型 -> (字节数, struct格式, 是否整数)
_DT_INFO = {
    'UBYTE': (1, 'B', True), 'SBYTE': (1, 'b', True),
    'UWORD': (2, 'H', True), 'SWORD': (2, 'h', True),
    'ULONG': (4, 'I', True), 'SLONG': (4, 'i', True),
    'FLOAT32_IEEE': (4, 'f', False), 'FLOAT64_IEEE': (8, 'd', False),
}

_DCM_HEAD_RE = re.compile(r'^(FESTWERTEBLOCK|GRUPPENKENNFELD|GRUPPENKENNLINIE|'
                          r'FESTKENNLINIE|FESTWERT|STUETZSTELLENVERTEILUNG)\s+'
                          r'([A-Za-z_]\w*)(.*)$')
_DCM_NUM_RE = re.compile(r'[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?')

_CHAR_TYPE_RE = re.compile(r'(?:Characteristic\s+Type|Type)\s*\*/\s*([A-Za-z_]\w*)')
_RECORD_LAYOUT_RE = re.compile(r'Record\s+Layout\s*\*/\s*([A-Za-z_]\w*)')
_COEFFS_RE = re.compile(r'COEFFS(?:_LINEAR)?\s+'
                        r'([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+'
                        r'([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)')
_CONVT_RE = re.compile(r'Conversion\s+Type\s*\*/\s*([A-Za-z_]\w*)')
_CM_REF_RE = re.compile(r'Conversion [Mm]ethod\s*\*/\s*([A-Za-z_]\w*)')
_AXIS_DESCR_RE = re.compile(r'/begin\s+AXIS_DESCR(.*?)/end\s+AXIS_DESCR', re.DOTALL)
_AXIS_TYPE_RE = re.compile(r'Axis\s+Type\s*\*/\s*([A-Za-z_]\w*)')
_AXIS_PTS_REF_RE = re.compile(r'AXIS_PTS_REF\s+([A-Za-z_]\w*)')
_AXIS_N_RE = re.compile(r'Number\s+of\s+Axis\s+Pts\s*\*/\s*(\d+)')
_RL_ENTRY_RE = re.compile(r'(FNC_VALUES|AXIS_PTS_X|AXIS_PTS_Y)\s+\d+\s+([A-Za-z_]\w*)'
                          r'(?:\s+(COLUMN_DIR|ROW_DIR))?')


# ==================== DCM 解析 ====================

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


# ==================== A2L 索引构建 ====================

def build_a2l_index(path, log=None):
    """解析 A2L, 建立 CHARACTERISTIC/AXIS_PTS/COMPU_METHOD/RECORD_LAYOUT 索引.
    返回 {'objects': {name: {...}}, 'cms': {...}, 'layouts': {...}, 'dirs': {...}}"""
    log = log or (lambda m: None)
    lines = _read_lines(path)
    blocks, _ = _parse_blocks(lines, need_text=True)
    objects, cms, layouts, dirs = {}, {}, {}, {}
    for b in blocks:
        if not b.get('name'):
            continue
        # 正则依赖注释关键字 (如 /* Record Layout */), 必须用原始文本
        t = re.sub(r'\s+', ' ', b['text'])
        typ = b['type']
        if typ in ('CHARACTERISTIC', 'AXIS_PTS'):
            addr_s = _get_addr(b)
            obj = {'name': b['name'], 'kind': typ, 'addr': None,
                   'layout': None, 'cm': None}
            if addr_s:
                try:
                    obj['addr'] = int(addr_s, 16)
                except ValueError:
                    pass
            m = _RECORD_LAYOUT_RE.search(t)
            if m:
                obj['layout'] = m.group(1)
            m = _CM_REF_RE.search(t)
            if m:
                obj['cm'] = m.group(1)
            if typ == 'CHARACTERISTIC':
                m = _CHAR_TYPE_RE.search(t)
                obj['char_type'] = m.group(1) if m else ''
                axes = []
                for am in _AXIS_DESCR_RE.finditer(t):
                    seg = am.group(1)
                    ax = {'type': None, 'cm': None, 'n': 0, 'ref': None}
                    m2 = _AXIS_TYPE_RE.search(seg)
                    if m2:
                        ax['type'] = m2.group(1)
                    m2 = _CM_REF_RE.search(seg)
                    if m2:
                        ax['cm'] = m2.group(1)
                    m2 = _AXIS_N_RE.search(seg)
                    if m2:
                        ax['n'] = int(m2.group(1))
                    m2 = _AXIS_PTS_REF_RE.search(seg)
                    if m2:
                        ax['ref'] = m2.group(1)
                    axes.append(ax)
                obj['axes'] = axes
            objects[b['name']] = obj
        elif typ == 'COMPU_METHOD':
            cm = {'conv': None, 'coeffs': None, 'byte_order': None}
            m = _CONVT_RE.search(t)
            if m:
                cm['conv'] = m.group(1)
            m = _COEFFS_RE.search(t)
            if m:
                cm['coeffs'] = tuple(float(x) for x in m.groups())
            m = re.search(r'BYTE_ORDER\s+(\w+)', t)
            if m:
                cm['byte_order'] = m.group(1)
            cms[b['name']] = cm
        elif typ == 'RECORD_LAYOUT':
            m = _RL_ENTRY_RE.search(t)
            if m:
                layouts[b['name']] = m.group(2)
                if m.group(1) == 'FNC_VALUES' and m.group(3):
                    dirs[b['name']] = m.group(3)
    log('  A2L 索引: 对象 %d (CHARACTERISTIC/AXIS_PTS), 转换方法 %d, 记录布局 %d' %
        (len(objects), len(cms), len(layouts)))
    return {'objects': objects, 'cms': cms, 'layouts': layouts, 'dirs': dirs}


# ==================== DCM 写入 HEX ====================

def dcm_to_hex(dcm_path, a2l_path, hex_path, out_path, log=None):
    """解析 DCM + A2L, 把标定数据编码为原始字节写入 HEX, 输出新文件"""
    t0 = time.time()
    log = log or (lambda m: None)

    log('[1/4] 解析 DCM ...')
    objs = parse_dcm(dcm_path, log)

    log('[2/4] 解析 A2L ...')
    idx = build_a2l_index(a2l_path, log)
    objects, cms, layouts = idx['objects'], idx['cms'], idx['layouts']
    dirs = idx['dirs']

    log('[3/4] 加载 HEX ...')
    mem = load_intel_hex(hex_path, log)
    lo, hi = min(mem), max(mem)

    log('[4/4] 编码并写入 ...')
    stats = Counter()
    warns = []

    def covered(addr, n):
        return lo <= addr and addr + n <= hi + 1 and addr + n - 1 <= hi

    def get_cm(name):
        return cms.get(name) if name else None

    def write_seq(name, addr, vals, cm_name, layout, tag):
        """把一组物理值编码后连续写入; 成功返回 True"""
        dt = layouts.get(layout)
        if not dt:
            warns.append('%s: 记录布局 %s 无数据类型' % (name, layout))
            stats['skip_conv'] += 1
            return False
        cm = get_cm(cm_name)
        if cm is None or cm['coeffs'] is None or cm['conv'] not in ('RAT_FUNC', None):
            warns.append('%s: 转换方法 %s 不支持 (TAB_VERB/缺失/无COEFFS)' % (name, cm_name))
            stats['skip_conv'] += 1
            return False
        size = _DT_INFO.get(dt, (0,))[0]
        if not size:
            warns.append('%s: 未知数据类型 %s' % (name, dt))
            stats['skip_conv'] += 1
            return False
        if not covered(addr, size * len(vals)):
            warns.append('%s: 地址 0x%X+%d 超出 HEX 覆盖范围' % (name, addr, size * len(vals)))
            stats['skip_range'] += 1
            return False
        for i, v in enumerate(vals):
            raw, w = encode_raw(v, cm['coeffs'], dt, cm['byte_order'])
            if raw is None:
                warns.append('%s: %s' % (name, w))
                stats['skip_conv'] += 1
                return False
            if w:
                warns.append('%s[%d]: %s' % (name, i, w))
            for j, bv in enumerate(raw):
                mem[addr + i * size + j] = bv
        stats[tag] += 1
        return True

    for name, o in objs.items():
        kind = o['kind']
        if kind == 'STUETZSTELLENVERTEILUNG':
            continue      # 轴数据随引用它的曲线/MAP 一起写
        ch = objects.get(name)
        if ch is None or ch['kind'] != 'CHARACTERISTIC':
            stats['skip_noa2l'] += 1
            continue
        addr = ch['addr']
        if not addr:
            warns.append('%s: A2L 中无有效 ECU 地址' % name)
            stats['skip_addr'] += 1
            continue

        if kind in ('FESTWERT', 'FESTWERTEBLOCK'):
            write_seq(name, addr, o['values'], ch['cm'], ch['layout'], 'w_fixed')
            continue

        # CURVE / MAP: 先写轴, 再写数值区.
        # DCM 的 ST/X 对应第 1 个 AXIS_DESCR, ST/Y 对应第 2 个 (按声明顺序, 与轴地址无关)
        axes = ch.get('axes', [])
        is_map = kind == 'GRUPPENKENNFELD'
        dims = [len(o['xs']), len(o['ys'])] if is_map else [len(o['xs'])]
        if len(axes) != len(dims):
            warns.append('%s: A2L 轴数 %d 与 DCM 维度 %s 不一致, 跳过写入' %
                         (name, len(axes), 'x'.join(str(v) for v in dims)))
            stats['skip_dim'] += 1
            continue
        bad = ['轴%d %s: DCM %d 点 != A2L %d 点' % (i + 1, axes[i]['ref'] or '',
               dims[i], axes[i]['n']) for i, ax in enumerate(axes)
               if ax['n'] and dims[i] != ax['n']]
        if bad:
            warns.append('%s: DCM 维度与 A2L 不一致 (%s), 跳过写入' %
                         (name, ', '.join(bad)))
            stats['skip_dim'] += 1
            continue
        nvals_need = dims[0] * dims[1] if is_map else dims[0]
        if len(o['values']) != nvals_need:
            warns.append('%s: 值个数 %d 与轴维度乘积 %d 不符, 跳过写入' %
                         (name, len(o['values']), nvals_need))
            stats['skip_dim'] += 1
            continue
        ok = True
        for ax_i, ax in enumerate(axes):
            if ax['type'] == 'FIX_AXIS':
                continue    # 隐式轴, 不占 ECU 存储, 只写数值区即可
            if ax['type'] != 'COM_AXIS' or not ax['ref']:
                warns.append('%s: 轴 %d 类型 %s 不支持, 跳过写入' %
                             (name, ax_i + 1, ax['type']))
                ok = False
                break
            axo = objects.get(ax['ref'])
            if axo is None or not axo['addr']:
                warns.append('%s: 轴对象 %s 无地址' % (name, ax['ref']))
                ok = False
                break
            axvals = o['xs'] if ax_i == 0 else o['ys']
            if not write_seq(name + '.' + ax['ref'], axo['addr'], axvals,
                             ax['cm'] or axo['cm'], axo['layout'], 'w_axis'):
                ok = False
                break
        if not ok:
            continue
        # 数值区: MAP 在 HEX 中按 COLUMN_DIR 存储 (轴1外层/轴2内层),
        # 而 DCM 的 WERT 按 ST/Y 逐行存放 (轴2外层/轴1内层), 需转置后写入
        vals = o['values']
        if is_map and dirs.get(ch['layout'], 'COLUMN_DIR') == 'COLUMN_DIR':
            nx, ny = dims
            vals = [o['values'][j * nx + i] for i in range(nx) for j in range(ny)]
        write_seq(name, addr, vals, ch['cm'], ch['layout'],
                  'w_map' if is_map else 'w_curve')

    save_intel_hex(out_path, mem)

    log('  写入完成: 标定量/块 %d, 曲线 %d, MAP %d, 轴 %d' %
        (stats['w_fixed'], stats['w_curve'], stats['w_map'], stats['w_axis']))
    log('  跳过: A2L无对象 %d, 地址无效 %d, HEX范围外 %d, 转换不支持 %d, 维度不一致 %d' %
        (stats['skip_noa2l'], stats['skip_addr'], stats['skip_range'],
         stats['skip_conv'], stats['skip_dim']))
    for w in warns[:200]:
        log('  [警告] ' + w)
    if len(warns) > 200:
        log('  [警告] ... 其余 %d 条略' % (len(warns) - 200))
    log('  输出: %s (耗时 %.1fs)' % (out_path, time.time() - t0))
    return {'stats': dict(stats), 'warns': warns}


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 5:
        print("用法: python dcm_handler.py <dcm_file> <a2l_file> <hex_file> <out_hex>")
        sys.exit(1)
    
    dcm_path, a2l_path, hex_path, out_path = sys.argv[1:5]
    try:
        result = dcm_to_hex(dcm_path, a2l_path, hex_path, out_path, log=print)
        st = result['stats']
        print(f"\n写入统计:")
        print(f"  标定量/块: {st.get('w_fixed', 0)}")
        print(f"  曲线: {st.get('w_curve', 0)}")
        print(f"  MAP: {st.get('w_map', 0)}")
        print(f"  轴: {st.get('w_axis', 0)}")
        print(f"  警告: {len(result['warns'])}")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)
