#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Intel HEX 文件处理模块 - 加载、保存、编码"""

import struct


# ==================== 常量定义 ====================

# A2L 数据类型 -> (字节数, struct格式, 是否整数)
_DT_INFO = {
    'UBYTE': (1, 'B', True), 'SBYTE': (1, 'b', True),
    'UWORD': (2, 'H', True), 'SWORD': (2, 'h', True),
    'ULONG': (4, 'I', True), 'SLONG': (4, 'i', True),
    'FLOAT32_IEEE': (4, 'f', False), 'FLOAT64_IEEE': (8, 'd', False),
}

# Record Layout 名称 -> 实际数据类型（从Record Layout定义中推断）
_RL_TYPE_MAP = {
    'Lookup1D_BOOLEAN': 'UBYTE',
    'Lookup1D_UBYTE': 'UBYTE',
    'Lookup1D_BYTE': 'SBYTE',
    'Lookup1D_UWORD': 'UWORD',
    'Lookup1D_WORD': 'SWORD',
    'Lookup1D_ULONG': 'ULONG',
    'Lookup1D_LONG': 'SLONG',
    'Lookup1D_FLOAT32_IEEE': 'FLOAT32_IEEE',
    'Lookup1D_FLOAT64_IEEE': 'FLOAT64_IEEE',
    'Lookup2D_BOOLEAN': 'UBYTE',
    'Lookup2D_UBYTE': 'UBYTE',
    'Lookup2D_BYTE': 'SBYTE',
    'Lookup2D_UWORD': 'UWORD',
    'Lookup2D_WORD': 'SWORD',
    'Lookup2D_ULONG': 'ULONG',
    'Lookup2D_LONG': 'SLONG',
    'Lookup2D_FLOAT32_IEEE': 'FLOAT32_IEEE',
    'Lookup2D_FLOAT64_IEEE': 'FLOAT64_IEEE',
    'Scalar_BOOLEAN': 'UBYTE',
    'Scalar_UBYTE': 'UBYTE',
    'Scalar_BYTE': 'SBYTE',
    'Scalar_UWORD': 'UWORD',
    'Scalar_SWORD': 'SWORD',
    'Scalar_ULONG': 'ULONG',
    'Scalar_LONG': 'SLONG',
    'Scalar_FLOAT32_IEEE': 'FLOAT32_IEEE',
    'Scalar_FLOAT64_IEEE': 'FLOAT64_IEEE',
}


def get_data_type(record_layout):
    """从Record Layout名称推断数据类型"""
    if not record_layout:
        return None
    
    # 先查映射表
    dt = _RL_TYPE_MAP.get(record_layout)
    if dt:
        return dt
    
    # 尝试从名称中提取数据类型
    upper = record_layout.upper()
    for dtype in _DT_INFO:
        if dtype in upper:
            return dtype
    
    return None


# ==================== 编码函数 ====================

def encode_raw(phys, coeffs, dtype, byte_order):
    """物理量编码为 HEX 原始字节. coeffs=(a,b,c,d,e,f) RAT_FUNC 系数.
    Simulink 生成的 COEFFS 为 phys→raw 方向 (longid 形如 "Q = V*100"),
    故直接正向求值: raw = (a·phys²+b·phys+c)/(d·phys²+e·phys+f).
    返回 (bytes, warn); 无法编码时返回 (None, 原因)"""
    info = _DT_INFO.get(dtype)
    if not info:
        return None, '未知数据类型 %s' % dtype
    size, fmt, is_int = info
    msb_first = byte_order == 'BYTE_ORDER_MSB_FIRST'
    endian = '>' if msb_first else '<'
    if not is_int:
        try:
            return struct.pack(endian + fmt, float(phys)), None
        except (OverflowError, ValueError):
            return None, '浮点值非法: %s' % phys
    if coeffs is None:
        return None, '无 COEFFS 系数'
    a, b, c, d, e, f = coeffs
    lo = 0 if fmt == 'B' else (-128 if fmt == 'b' else
                                0 if fmt == 'H' else (-32768 if fmt == 'h' else
                                                       0 if fmt == 'I' else -2147483648))
    hi = (255 if fmt == 'B' else 127 if fmt == 'b' else
          65535 if fmt == 'H' else 32767 if fmt == 'h' else
          4294967295 if fmt == 'I' else 2147483647)
    den = d * phys * phys + e * phys + f
    if den == 0:
        return None, '转换公式分母为 0'
    x = (a * phys * phys + b * phys + c) / den
    xr = int(round(x))
    warn = None
    if xr < lo or xr > hi:
        warn = '值 %s 编码 %d 超出 %s 范围, 已截断' % (phys, xr, dtype)
        xr = max(lo, min(hi, xr))
    return struct.pack(endian + fmt, xr), warn


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


def save_intel_hex(path, mem, rec_len=32):
    """按连续段输出 Intel HEX (记录04 扩展线性地址 + 数据记录 + EOF)"""
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
    for s, e in segs:
        off = s
        while off < e:
            hi = off >> 16
            if hi != cur_base:
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
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')


# ==================== 标定值读写 ====================

def read_calibration_value(mem, addr, data_type, coeffs=None, byte_order=None):
    """从内存读取标定量物理值
    
    根据ASAM MCD-2 MC标准：
    - COEFFS a b c d e f
    - 公式: raw = (a*phys^2 + b*phys + c) / (d*phys^2 + e*phys + f)
    - 需要反向求解 phys
    
    Args:
        mem: 内存字典 {地址: 字节值}
        addr: 标定量地址
        data_type: 数据类型
        coeffs: COEFFS (a,b,c,d,e,f)
        byte_order: 字节序
    
    Returns:
        (物理值, 错误信息)
    """
    info = _DT_INFO.get(data_type)
    if not info:
        return None, '未知数据类型: %s' % data_type
    
    size, fmt, is_int = info
    msb_first = byte_order == 'BYTE_ORDER_MSB_FIRST'
    endian = '>' if msb_first else '<'
    
    # 检查地址是否在内存中
    for i in range(size):
        if (addr + i) not in mem:
            return None, '地址 0x%X+%d 不在HEX覆盖范围内' % (addr, i)
    
    # 读取原始字节
    raw_bytes = bytes(mem[addr + i] for i in range(size))
    
    # 解包得到原始值
    try:
        raw_value = struct.unpack(endian + fmt, raw_bytes)[0]
    except struct.error as e:
        return None, '解包失败: %s' % str(e)
    
    # 检查nan
    if isinstance(raw_value, float) and raw_value != raw_value:
        return None, '原始值为nan'
    
    # 无系数，直接返回原始值
    if coeffs is None:
        return raw_value, None
    
    # 有系数，需要反算物理值
    # raw = (a*phys^2 + b*phys + c) / (d*phys^2 + e*phys + f)
    a, b, c, d, e, f = coeffs
    raw = raw_value
    
    # 检查是否是线性情况 (a=0, d=0)
    if a == 0 and d == 0:
        # 线性: raw = (b*phys + c) / (e*phys + f)
        # raw*(e*phys + f) = b*phys + c
        # raw*e*phys + raw*f = b*phys + c
        # (raw*e - b)*phys = c - raw*f
        # phys = (c - raw*f) / (raw*e - b)
        
        denom = raw * e - b
        if denom == 0:
            return None, '转换公式分母为0 (raw*e - b == 0)'
        phys = (c - raw * f) / denom
    else:
        # 一般二次情况
        # raw = (a*phys^2 + b*phys + c) / (d*phys^2 + e*phys + f)
        # raw*(d*phys^2 + e*phys + f) = a*phys^2 + b*phys + c
        # raw*d*phys^2 + raw*e*phys + raw*f = a*phys^2 + b*phys + c
        # (raw*d - a)*phys^2 + (raw*e - b)*phys + (raw*f - c) = 0
        
        A = raw * d - a
        B = raw * e - b
        C = raw * f - c
        
        if A == 0:
            # 线性方程
            if B == 0:
                return None, '无法求解物理值'
            phys = -C / B
        else:
            # 二次方程: A*phys^2 + B*phys + C = 0
            discriminant = B * B - 4 * A * C
            if discriminant < 0:
                return None, '无实数解 (判别式 < 0)'
            sqrt_disc = discriminant ** 0.5
            phys1 = (-B + sqrt_disc) / (2 * A)
            phys2 = (-B - sqrt_disc) / (2 * A)
            # 选择更合理的解
            phys = phys1 if abs(phys1) <= abs(phys2) else phys2
    
    # 检查nan
    if phys != phys:
        return None, '转换结果为nan'
    
    return phys, None


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
    msb_first = byte_order == 'BYTE_ORDER_MSB_FIRST'
    endian = '>' if msb_first else '<'
    
    if not is_int:
        # 浮点类型直接打包
        try:
            raw_bytes = struct.pack(endian + fmt, float(phys_value))
        except (OverflowError, ValueError) as e:
            return False, '浮点值非法: %s' % str(e)
    else:
        # 整数类型需要正向编码
        if coeffs is None:
            # 无系数，直接使用整数值
            try:
                raw_bytes = struct.pack(endian + fmt, int(round(phys_value)))
            except (OverflowError, ValueError) as e:
                return False, '整数值非法: %s' % str(e)
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
            
            # 检查范围
            lo = 0 if fmt == 'B' else (-128 if fmt == 'b' else
                                        0 if fmt == 'H' else (-32768 if fmt == 'h' else
                                                               0 if fmt == 'I' else -2147483648))
            hi = (255 if fmt == 'B' else 127 if fmt == 'b' else
                  65535 if fmt == 'H' else 32767 if fmt == 'h' else
                  4294967295 if fmt == 'I' else 2147483647)
            
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