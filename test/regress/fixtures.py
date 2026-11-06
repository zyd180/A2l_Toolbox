#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回归夹具: 在临时目录合成 A2L + HEX (不依赖 test/ 下的 379MB 真机样本).

设计原则:
  - 覆盖最容易写错的机制: COEFFS 方向 (Simulink phys->raw)、字节序、COM_AXIS 轴值联动、
    FIX_AXIS 隐式轴、MAP 的 COLUMN_DIR 存储方向、MEMORY_SEGMENT 段内 0xFF 填充
  - 期望值全部手算写下 (见 EXPECTED), 不从被测代码推, 否则测的是"自己和自己相等"
  - HEX 用本文件自带的独立 writer 生成, 不用 core.hex_handler.save_intel_hex,
    避免夹具与被测代码同源 (那样写入端坏了夹具就一起坏, 测试还绿)

地址分配 (全部小端 UWORD, 2 字节/点):
  0x1000 Sca_Val   VALUE   raw 50         -> phys 5.0 (CM x10)
  0x1002 Blk_Arr   VAL_BLK raw 1,2,3,4
  0x100A Cur_Curve CURVE   raw 10..50     COM_AXIS -> AX_Cur
  0x1014 AX_Cur    AXIS_PTS raw 0,100,200,300,400
  0x101E Map_2D    MAP     raw 11,12,21,22,31,32 (COLUMN_DIR: k=c*ny+r)
  0x102A AX_MapX   AXIS_PTS raw 1,2,3
  0x1030 AX_MapY   AXIS_PTS raw 7,8
  0x1034 Fix_Curve CURVE   raw 5..9       FIX_AXIS_PAR_DIST -2 1 5 -> 轴 [-2,-1,0,1,2]
  段: 0x1000 长度 0x60 -> 0x1000..0x105F; 数据止于 0x103D, 故 0x103E..0x105F 应被补 0xFF
"""

import os

SEG_START = 0x1000
SEG_SIZE = 0x60

CMS = [
    # (name, longid, coeffs, unit, fmt)
    ('T_CM_Uint', 'Q = V', '0 1 0 0 0 1', '""', '%3.0'),
    ('T_CM_x10', 'Q = V*10.000000', '0 10 0 0 0 1', '"km/h"', '%6.2'),
]

LAYOUTS = [
    ('Scalar_UWORD', 'FNC_VALUES  1 UWORD COLUMN_DIR DIRECT'),
    ('Lookup1D_UWORD', 'FNC_VALUES  1 UWORD COLUMN_DIR DIRECT'),
    ('Lookup2D_UWORD',
     'FNC_VALUES  1 UWORD COLUMN_DIR DIRECT\n'
     '      AXIS_PTS_X  2 UWORD INDEX_INCR DIRECT\n'
     '      AXIS_PTS_Y  3 UWORD INDEX_INCR DIRECT'),
]

# (name, addr, layout, cm, n, raw values)
AXIS_PTS = [
    ('AX_Cur', 0x1014, 'Lookup1D_UWORD', 'T_CM_Uint', 5, [0, 100, 200, 300, 400]),
    ('AX_MapX', 0x102A, 'Lookup1D_UWORD', 'T_CM_Uint', 3, [1, 2, 3]),
    ('AX_MapY', 0x1030, 'Lookup1D_UWORD', 'T_CM_Uint', 2, [7, 8]),
]

OBJECTS = [
    dict(name='Sca_Val', addr=0x1000, layout='Scalar_UWORD', cm='T_CM_x10',
         ctype='VALUE', values=[50], lower=0, upper=100, number=None, axes=[]),
    dict(name='Blk_Arr', addr=0x1002, layout='Scalar_UWORD', cm='T_CM_Uint',
         ctype='VAL_BLK', values=[1, 2, 3, 4], lower=0, upper=65535, number=4, axes=[]),
    dict(name='Cur_Curve', addr=0x100A, layout='Lookup1D_UWORD', cm='T_CM_Uint',
         ctype='CURVE', values=[10, 20, 30, 40, 50], lower=0, upper=65535, number=None,
         axes=[dict(type='COM_AXIS', cm='T_CM_Uint', n=5, ref='AX_Cur')]),
    dict(name='Map_2D', addr=0x101E, layout='Lookup2D_UWORD', cm='T_CM_Uint',
         ctype='MAP', values=[11, 12, 21, 22, 31, 32], lower=0, upper=65535, number=None,
         axes=[dict(type='COM_AXIS', cm='T_CM_Uint', n=3, ref='AX_MapX'),
               dict(type='COM_AXIS', cm='T_CM_Uint', n=2, ref='AX_MapY')]),
    dict(name='Fix_Curve', addr=0x1034, layout='Lookup1D_UWORD', cm='T_CM_Uint',
         ctype='CURVE', values=[5, 6, 7, 8, 9], lower=0, upper=65535, number=None,
         axes=[dict(type='FIX_AXIS', cm='T_CM_Uint', n=5, ref=None,
                    fix='FIX_AXIS_PAR_DIST -2 1 5')]),
]

# 手算期望 (字段名 -> 物理值列表)
EXPECTED = {
    'Sca_Val': [5.0],                       # raw 50 / 10
    'Blk_Arr': [1.0, 2.0, 3.0, 4.0],
    'Cur_Curve': [10.0, 20.0, 30.0, 40.0, 50.0],
    'AX_Cur': [0.0, 100.0, 200.0, 300.0, 400.0],
    'Map_2D': [11.0, 12.0, 21.0, 22.0, 31.0, 32.0],
    'AX_MapX': [1.0, 2.0, 3.0],
    'AX_MapY': [7.0, 8.0],
    'Fix_Curve': [5.0, 6.0, 7.0, 8.0, 9.0],
}
EXPECTED_FIX_AXIS = [-2.0, -1.0, 0.0, 1.0, 2.0]

# 段内应为 0xFF 的填充区 (数据止于 0x103D)
FILL_RANGE = (0x103E, SEG_START + SEG_SIZE)     # [start, end)


# ==================== A2L 生成 ====================

_CM_TPL = """    /begin COMPU_METHOD
      /* Name of CompuMethod    */      {name}
      /* Long identifier        */      "{longid}"
      /* Conversion Type        */      RAT_FUNC
      /* Format                 */      "{fmt}"
      /* Units                  */      {unit}
      /* Coefficients           */      COEFFS {coeffs}
    /end COMPU_METHOD
"""

_LAYOUT_TPL = """    /begin RECORD_LAYOUT {name}
      {body}
    /end RECORD_LAYOUT
"""

_AXIS_TPL = """    /begin AXIS_PTS
      /* Name                   */      {name}
      /* Long Identifier        */      "axis"
      /* ECU Address            */      0x{addr:08X}
      /* Input Quantity         */      Dummy
      /* Record Layout          */      {layout}
      /* Maximum Difference     */      0
      /* Conversion Method      */      {cm}
      /* Number of Axis Pts     */      {n}
      /* Lower Limit            */      -655.36
      /* Upper Limit            */      655.34
    /end AXIS_PTS
"""

_DESCR_TPL = """      /begin AXIS_DESCR
        /* Axis Type            */      {type}
        /* Reference to Input   */      Dummy
        /* Conversion Method    */      {cm}
        /* Number of Axis Pts   */      {n}
        /* Lower Limit          */      -655.36
        /* Upper Limit          */      655.34
{tail}
      /end AXIS_DESCR
"""

_CHAR_TPL = """    /begin CHARACTERISTIC
      /* Name                   */      {name}
      /* Long Identifier        */      "{doc}"
      /* Characteristic Type    */      {ctype}
      /* ECU Address            */      0x{addr:08X}
      /* Record Layout          */      {layout}
      /* Maxdiff                */      0
      /* Conversion Method      */      {cm}
      /* Lower Limit            */      {lower}
      /* Upper Limit            */      {upper}
{number}{axes}    /end CHARACTERISTIC
"""

_MEMSEG_TPL = """    /begin MEMORY_SEGMENT
      T_Cal "Calibration data Segment" DATA FLASH INTERN 0x{start:08X} 0x{size:08X} -1 -1 -1 -1 -1
    /end MEMORY_SEGMENT
"""


def a2l_text(with_mem_segment=True):
    """生成夹具 A2L 文本"""
    parts = ['ASAP2_VERSION 1 61', '/begin PROJECT DEMO "demo"', '',
             '  /begin MODULE DEMO "demo module"', '']

    for name, longid, coeffs, unit, fmt in CMS:
        parts.append(_CM_TPL.format(name=name, longid=longid, coeffs=coeffs,
                                    unit=unit, fmt=fmt))
    for name, body in LAYOUTS:
        parts.append(_LAYOUT_TPL.format(name=name, body=body))
    if with_mem_segment:
        parts.append(_MEMSEG_TPL.format(start=SEG_START, size=SEG_SIZE))

    for name, addr, layout, cm, n, _vals in AXIS_PTS:
        parts.append(_AXIS_TPL.format(name=name, addr=addr, layout=layout, cm=cm, n=n))

    for o in OBJECTS:
        axes = ''
        for ax in o['axes']:
            if ax['type'] == 'FIX_AXIS':
                tail = '        ' + ax['fix']
            else:
                tail = '        AXIS_PTS_REF                    %s' % ax['ref']
            axes += _DESCR_TPL.format(type=ax['type'], cm=ax['cm'], n=ax['n'], tail=tail)
        number = ('      NUMBER {n}\n'.format(n=o['number']) if o['number'] else '')
        parts.append(_CHAR_TPL.format(
            name=o['name'], doc='demo %s' % o['name'], ctype=o['ctype'],
            addr=o['addr'], layout=o['layout'], cm=o['cm'],
            lower=o['lower'], upper=o['upper'], number=number, axes=axes))

    parts.append("""    /begin FUNCTION
      T_Func "demo function"
      /begin DEF_CHARACTERISTIC
        Sca_Val
        Blk_Arr
        Cur_Curve
        Map_2D
        Fix_Curve
      /end DEF_CHARACTERISTIC
      /begin REF_CHARACTERISTIC
        AX_Cur
        AX_MapX
        AX_MapY
      /end REF_CHARACTERISTIC
      /begin IN_MEASUREMENT
      /end IN_MEASUREMENT
    /end FUNCTION
""")
    parts += ['  /end MODULE', '/end PROJECT', '']
    return '\n'.join(parts)


# ==================== HEX 生成 (独立实现) ====================

def mem_map(zeroed=False):
    """夹具内存 {addr: byte}: 全部为小端 UWORD"""
    mem = {}
    for _n, addr, _l, _c, _cnt, vals in AXIS_PTS:
        for i, v in enumerate(vals):
            v = 0 if zeroed else v
            mem[addr + 2 * i] = v & 0xFF
            mem[addr + 2 * i + 1] = (v >> 8) & 0xFF
    for o in OBJECTS:
        for i, v in enumerate(o['values']):
            v = 0 if zeroed else v
            mem[o['addr'] + 2 * i] = v & 0xFF
            mem[o['addr'] + 2 * i + 1] = (v >> 8) & 0xFF
    return mem


def _rec(payload):
    chk = (256 - (sum(payload) & 0xFF)) & 0xFF
    return ':' + ''.join('%02X' % b for b in payload + [chk])


def intel_hex_text(mem, rec_len=16):
    """独立的最小 Intel HEX writer (记录 04 + 记录 00 + EOF)"""
    lines = []
    addrs = sorted(mem)
    i = 0
    while i < len(addrs):
        start = addrs[i]
        j = i
        while j + 1 < len(addrs) and addrs[j + 1] == addrs[j] + 1 and (j - i + 1) < rec_len:
            j += 1
        chunk = [mem[a] for a in addrs[i:j + 1]]
        hi = start >> 16
        lines.append(_rec([2, 0, 0, 4, (hi >> 8) & 0xFF, hi & 0xFF]))
        lines.append(_rec([len(chunk), (start >> 8) & 0xFF, start & 0xFF, 0] + chunk))
        i = j + 1
    lines.append(':00000001FF')
    return '\r\n'.join(lines) + '\r\n'


def write_fixture(outdir, with_mem_segment=True, zeroed=False):
    """写出夹具文件, 返回 (a2l_path, hex_path)"""
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    a2l_path = os.path.join(outdir, 'demo.a2l')
    hex_path = os.path.join(outdir, 'demo.hex')
    with open(a2l_path, 'w', encoding='utf-8', newline='') as f:
        f.write(a2l_text(with_mem_segment))
    with open(hex_path, 'w', encoding='utf-8', newline='') as f:
        f.write(intel_hex_text(mem_map(zeroed)))
    return a2l_path, hex_path
