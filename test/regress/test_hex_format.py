#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""HEX 读写与记录格式回归 (hex_handler).

重点: 输出必须与 INCA 导出格式一致 (CRLF + 文件尾 \\x1a + 段首/段边界重发 ELADR),
以及 load -> save -> load 的字节等价.
"""

import os

import _harness  # noqa: F401  (设置 sys.path)
import fixtures
from core.hex_handler import load_intel_hex, save_intel_hex, write_calibration_value


def run(suite):
    tmp = suite.tmpdir()
    mem = fixtures.mem_map()

    # 1) 载入独立 writer 生成的夹具 (验证 loader 不依赖自身 writer)
    a2l_path, hex_path = fixtures.write_fixture(tmp)
    loaded = load_intel_hex(hex_path)
    suite.eq('load_intel_hex 读回字节与夹具一致', loaded, mem)
    suite.eq('夹具地址范围', (min(loaded), max(loaded)), (0x1000, 0x103D))

    # 2) 往返等价
    out = os.path.join(tmp, 'roundtrip.hex')
    save_intel_hex(out, mem)
    suite.eq('save->load 字节等价', load_intel_hex(out), mem)

    # 3) 记录格式对标 INCA
    raw = open(out, 'rb').read()
    suite.check('文件以 CRLF 结尾并带 DOS EOF 0x1a', raw.endswith(b'\r\n\x1a'),
                '尾部=%r' % raw[-6:])
    lines = raw.decode('ascii').split('\r\n')
    suite.check('首条记录为扩展线性地址 (类型04)', lines[0].startswith(':02000004'),
                '首行=%r' % lines[0])
    suite.check('末条记录为 EOF', ':00000001FF' in lines, '')
    # 数据记录长度 <= 32 字节
    data_lens = []
    for ln in lines:
        if ln.startswith(':') and len(ln) > 9 and ln[7:9] == '00':
            data_lens.append(int(ln[1:3], 16))
    suite.check('数据记录长度均 <= 32 字节', data_lens and max(data_lens) <= 32,
                '最大=%s' % (max(data_lens) if data_lens else None))
    # 无裸 LF
    suite.check('不含裸 LF 行尾', b'\n' not in raw.replace(b'\r\n', b''), '')

    # 4) 段边界强制重发 ELADR: 地址连续但指定 eladr_addrs 时应多出一条类型04记录
    cont = dict((0x2000 + i, 0xAA) for i in range(0x40))
    p_plain = os.path.join(tmp, 'plain.hex')
    p_eladr = os.path.join(tmp, 'eladr.hex')
    save_intel_hex(p_plain, cont)
    save_intel_hex(p_eladr, cont, eladr_addrs={0x2020})
    n4_plain = open(p_plain, 'rb').read().count(b':02000004')
    n4_eladr = open(p_eladr, 'rb').read().count(b':02000004')
    suite.check('段边界处强制重发 ELADR', n4_eladr > n4_plain,
                '%d -> %d' % (n4_plain, n4_eladr))
    suite.eq('重发 ELADR 不影响字节内容', load_intel_hex(p_eladr), cont)

    # 5) 值编码: 小端 + 范围保护
    m = {}
    ok, err = write_calibration_value(m, 0x3000, 5.0, 'UWORD',
                                      (0, 10.0, 0, 0, 0, 1), 'MSB_LAST')
    suite.check('UWORD 编码成功', ok, str(err))
    suite.eq('UWORD 小端字节 (5.0*10=50 -> 0x32 0x00)',
             (m.get(0x3000), m.get(0x3001)), (0x32, 0x00))

    m2 = {}
    ok2, err2 = write_calibration_value(m2, 0x3000, 5.0, 'UWORD',
                                        (0, 10.0, 0, 0, 0, 1), 'MSB_FIRST')
    suite.check('显式 MSB_FIRST 生效',
                ok2 and (m2.get(0x3000), m2.get(0x3001)) == (0x00, 0x32),
                str((ok2, m2)))

    m3 = {}
    try:
        ok3, err3 = write_calibration_value(m3, 0x3000, 1e6, 'UBYTE', None, None)
        rejected = (not ok3) and not m3
        detail = 'ok=%s err=%s mem=%r' % (ok3, err3, m3)
    except Exception as e:      # 原实现此处会抛 struct.error 而非返回错误
        rejected = False
        detail = '抛异常 %s: %s' % (type(e).__name__, e)
    suite.check('整数超范围被拒绝且不写内存 (返回错误而非抛异常)', rejected, detail)

    # 6) 浮点直接打包
    m4 = {}
    ok4, err4 = write_calibration_value(m4, 0x4000, 1.5, 'FLOAT32_IEEE', None, 'MSB_LAST')
    import struct
    suite.check('FLOAT32 直接打包', ok4 and
                bytes(m4[0x4000 + i] for i in range(4)) == struct.pack('<f', 1.5), str(err4))
