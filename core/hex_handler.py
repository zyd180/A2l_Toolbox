#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Intel HEX 文件处理模块 - 读写 + 标定值写入 (物理值 -> 原始字节编码)

值解码 (原始字节 -> 物理值) 由 core.calib_engine.CalibSession 负责, 本模块不再保留
第二份实现, 避免 COEFFS 方向/字节序在两处各写一遍而出现分叉.
"""

import struct


# ==================== 常量定义 ====================

# A2L 数据类型 -> (字节数, struct格式, 是否整数)
_DT_INFO = {
    'UBYTE': (1, 'B', True), 'SBYTE': (1, 'b', True),
    'UWORD': (2, 'H', True), 'SWORD': (2, 'h', True),
    'ULONG': (4, 'I', True), 'SLONG': (4, 'i', True),
    'FLOAT32_IEEE': (4, 'f', False), 'FLOAT64_IEEE': (8, 'd', False),
}

# 整数类型的可取范围 (struct 格式 -> (lo, hi)), 打包前显式校验用
_INT_RANGE = {
    'B': (0, 255), 'b': (-128, 127),
    'H': (0, 65535), 'h': (-32768, 32767),
    'I': (0, 4294967295), 'i': (-2147483648, 2147483647),
}

# ==================== HEX 文件操作 ====================

def load_intel_hex(path, log=None):
    """解析 Intel HEX. 返回 {绝对地址: 字节值}, 校验和错误即抛异常"""
    log = log or (lambda m: None)
    mem = {}
    base = 0
    n_rec = 0
    with open(path, 'r', encoding='utf-8', errors='surrogateescape') as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if line[0] != ':':
                raise ValueError('第 %d 行不是有效的 Intel HEX 记录' % ln)
            try:
                raw = bytes.fromhex(line[1:])
            except ValueError:
                raise ValueError('第 %d 行包含非法十六进制字符' % ln)
            if len(raw) < 5 or sum(raw) & 0xFF:
                raise ValueError('第 %d 行长度或校验和错误' % ln)
            cnt, off, rtype = raw[0], (raw[1] << 8) | raw[2], raw[3]
            data = raw[4:-1]
            if len(data) != cnt:
                raise ValueError('第 %d 行字节数与长度字段不符' % ln)
            if rtype == 0:
                addr = base + off
                for i, bv in enumerate(data):
                    mem[addr + i] = bv
            elif rtype == 1:
                break
            elif rtype == 2:
                base = ((data[0] << 8) | data[1]) << 4
            elif rtype == 4:
                base = ((data[0] << 8) | data[1]) << 16
            n_rec += 1
    log('  HEX 记录数: %d, 字节数: %d (0x%X ~ 0x%X)' %
        (n_rec, len(mem), min(mem), max(mem)) if mem else '  HEX 无数据记录')
    return mem


def save_intel_hex(path, mem, rec_len=32, eladr_addrs=None):
    """按连续段输出 Intel HEX (记录04 扩展线性地址 + 数据记录 + EOF).
    eladr_addrs: 需要强制重发 ELADR 的地址 (如 MEMORY_SEGMENT 段边界, 对标 INCA:
    段切换处即使地址连续也重发地址记录)"""
    addrs = sorted(mem)
    segs = []
    s = addrs[0]
    p = addrs[0]
    for a in addrs[1:]:
        if a != p + 1:
            segs.append((s, p + 1))
            s = a
        p = a
    segs.append((s, p + 1))
    lines = []
    cur_base = None
    eladr_set = eladr_addrs or ()
    for s, e in segs:
        cur_base = None    # 每个连续段强制重发 ELADR (对标 INCA 导出的记录序列)
        off = s
        while off < e:
            hi = off >> 16
            if hi != cur_base or off in eladr_set:
                rec = bytes([2, 0, 0, 4, hi >> 8, hi & 0xFF])
                lines.append(':%s%02X' % (rec.hex().upper(),
                                          (256 - (sum(rec) & 0xFF)) & 0xFF))
                cur_base = hi
            n = min(rec_len, e - off, 0x10000 - (off & 0xFFFF))
            low = off & 0xFFFF
            payload = bytes([n, low >> 8, low & 0xFF, 0]) + \
                bytes(mem[off + i] for i in range(n))
            lines.append(':%s%02X' % (payload.hex().upper(),
                                      (256 - (sum(payload) & 0xFF)) & 0xFF))
            off += n
    lines.append(':00000001FF')
    # CRLF 行尾 + DOS EOF 控制符 \x1a (对标 INCA 导出)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\r\n'.join(lines) + '\r\n\x1a')


# ==================== 标定值读写 ====================

def write_calibration_value(mem, addr, phys_value, data_type, coeffs=None, byte_order=None):
    """将物理值写入内存
    
    根据ASAM MCD-2 MC标准：
    - COEFFS a b c d e f
    - 公式: raw = (a*phys^2 + b*phys + c) / (d*phys^2 + e*phys + f)
    
    Args:
        mem: 内存字典 {地址: 字节值}
        addr: 标定量地址
        phys_value: 物理值
        data_type: 数据类型
        coeffs: COEFFS (a,b,c,d,e,f)
        byte_order: 字节序
    
    Returns:
        (成功标志, 错误信息)
    """
    info = _DT_INFO.get(data_type)
    if not info:
        return False, '未知数据类型: %s' % data_type
    
    size, fmt, is_int = info
    # 字节序声明有多种写法: ASAP2 标准为 MSB_FIRST/MSB_LAST, 部分工具输出
    # BYTE_ORDER_MSB_FIRST / MSB_LAST_MOTOROLA。必须与 calib_engine.cm_byte_order
    # 认的集合一致, 否则会出现"读按大端解码、写按小端编码"的不对称。
    msb_first = byte_order in ('MSB_FIRST', 'BYTE_ORDER_MSB_FIRST', 'MSB_LAST_MOTOROLA')
    endian = '>' if msb_first else '<'
    lo, hi = _INT_RANGE[fmt] if is_int else (None, None)

    if not is_int:
        # 浮点类型直接打包
        try:
            raw_bytes = struct.pack(endian + fmt, float(phys_value))
        except (OverflowError, ValueError) as e:
            return False, '浮点值非法: %s' % str(e)
    else:
        # 整数类型需要正向编码
        if coeffs is None:
            # 无系数, 物理值即原始值; 同样要做范围检查, 否则 struct.pack 抛异常而非返回错误
            raw_int = int(round(float(phys_value)))
            if raw_int < lo or raw_int > hi:
                return False, '值 %d 超出 %s 范围 [%d, %d]' % (raw_int, data_type, lo, hi)
            try:
                raw_bytes = struct.pack(endian + fmt, raw_int)
            except struct.error as e:
                return False, '打包失败: %s' % str(e)
        else:
            # 使用COEFFS正向编码
            # raw = (a*phys^2 + b*phys + c) / (d*phys^2 + e*phys + f)
            a, b, c, d, e, f = coeffs
            phys = phys_value

            denom = d * phys * phys + e * phys + f
            if denom == 0:
                return False, '转换公式分母为0'

            raw = (a * phys * phys + b * phys + c) / denom
            raw_int = int(round(raw))

            if raw_int < lo or raw_int > hi:
                return False, '编码值 %d 超出 %s 范围 [%d, %d]' % (raw_int, data_type, lo, hi)

            try:
                raw_bytes = struct.pack(endian + fmt, raw_int)
            except struct.error as e:
                return False, '打包失败: %s' % str(e)
    
    # 写入内存
    for i, bv in enumerate(raw_bytes):
        mem[addr + i] = bv
    
    return True, None


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python hex_handler.py <hex_file>")
        sys.exit(1)
    
    try:
        mem = load_intel_hex(sys.argv[1], log=print)
        print(f"\n字节数: {len(mem)}")
        print(f"地址范围: 0x{min(mem):08X} - 0x{max(mem):08X}")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)