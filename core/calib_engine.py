#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在线标定引擎 - CalibSession: A2L 元数据索引 + HEX 内存 + 修改跟踪 + Undo/Redo

对标 INCA 的数据内核:
- 完整解析 COMPU_METHOD (Conversion/COEFFS/BYTE_ORDER/Format/Units)
- 解析 RECORD_LAYOUT 的 FNC_VALUES/AXIS_PTS_X/Y/Z 真实数据类型 (不再按名称猜测)
- 解析 CHARACTERISTIC 的 Lower/Upper Limit 与 FORMAT
- AXIS_DESCR 全轴型支持, FIX_AXIS_PAR 隐式轴直接生成轴值
- FUNCTION 与 GROUP 双层级归属
- 单元格级脏标记 (与加载时原始字节快照比对), 命令式 Undo/Redo
"""

import re
import struct

from core.hex_handler import (
    load_intel_hex, save_intel_hex,
    _DT_INFO,
)

from core.sync_engine import _read_lines, _parse_blocks


# ==================== 数据类型辅助 ====================

_INT_RANGE = {
    'B': (0, 255), 'b': (-128, 127),
    'H': (0, 65535), 'h': (-32768, 32767),
    'I': (0, 4294967295), 'i': (-2147483648, 2147483647),
}


def _norm_text(text):
    return re.sub(r'\s+', ' ', text)


# 块内注释关键字取值模式 (依赖 /* xxx */ 注释格式, 用归一化文本匹配)
_CM_REF_RE = re.compile(r'Conversion [Mm]ethod\s*\*/\s*([A-Za-z_]\w*)')
_NAME_RE = re.compile(r'/\*\s*Name(?:\s+of\s+\w+)?\s*\*/\s+([A-Za-z_]\w*)')
_LONGID_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_CHAR_TYPE_RE = re.compile(r'(?:Characteristic\s+Type|Type)\s*\*/\s*([A-Za-z_]\w*)')
_LOWER_RE = re.compile(r'Lower [Ll]imit\s*\*/\s*([-+]?[\d.]+(?:[eE][+-]?\d+)?)')
_UPPER_RE = re.compile(r'Upper [Ll]imit\s*\*/\s*([-+]?[\d.]+(?:[eE][+-]?\d+)?)')
_FORMAT_RE = re.compile(r'\bFORMAT\s*"([^"]*)"')
_UNIT_RE = re.compile(r'(?:Units|Unit|SI_UNIT)\s*\*/\s*"([^"]*)"')
_CONV_RE = re.compile(r'Conversion Type\s*\*/\s*([A-Za-z_]\w*)')
_COEFFS_RE = re.compile(r'COEFFS(?:_LINEAR)?\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)'
                        r'\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)')
_BYTE_ORDER_RE = re.compile(r'BYTE_ORDER\s+(\w+)')
_FNC_VALUES_RE = re.compile(r'FNC_VALUES\s+\d+\s+([A-Za-z_]\w*)(?:\s+(COLUMN_DIR|ROW_DIR))?')
_AXIS_XYZ_RE = re.compile(r'AXIS_PTS_([XYZ])\s+\d+\s+([A-Za-z_]\w*)')
_NUM_RE = re.compile(r'NUMBER\s+(\d+)')
_ECU_ADDR_GET_RE = re.compile(r'(?:ECU_ADDRESS|ECU\s+Address\s*\*/)\s*(0[xX][0-9A-Fa-f]+)')
_AXIS_DESCR_RE = re.compile(r'/begin\s+AXIS_DESCR(.*?)/end\s+AXIS_DESCR', re.DOTALL)
_AXIS_TYPE_RE = re.compile(r'Axis\s+Type\s*\*/\s*([A-Za-z_]\w*)')
_AXIS_PTS_REF_RE = re.compile(r'AXIS_PTS_REF\s+([A-Za-z_]\w*)')
_AXIS_N_RE = re.compile(r'Number of Axis Pts\s*\*/\s*(\d+)')
_FIX_PAR_RE = re.compile(r'/begin\s+(FIX_AXIS_PAR|FIX_AXIS_PAR_DIST)\s*'
                         r'([-+\d.eE+]+)\s+([-+\d.eE+]+)\s+(\d+)')

# 旧版名称推断兜底 (Record Layout 名称 -> 数据类型)


def infer_dtype_from_name(layout_name):
    """Record Layout 名称 -> 数据类型 (仅作解析失败时的兜底)"""
    if not layout_name:
        return None
    for suffix in _DT_INFO:
        if layout_name.endswith(suffix):
            return suffix
    upper = layout_name.upper()
    for dt in _DT_INFO:
        if dt in upper:
            return dt
    return None


def format_value(v, fmt=None):
    """按 A2L FORMAT 字符串显示数值; A2L 的 "%5.2" 等价于 printf "%5.2f\""""
    if v is None:
        return ''
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return str(v)
    if fv != fv:
        return 'nan'
    if fmt:
        f = fmt.strip()
        if f and '%' in f:
            pf = f if f.endswith(('d', 'e', 'E', 'f', 'g', 'G')) else f + 'f'
            try:
                return pf % fv
            except TypeError:
                pass
    return '%.6g' % fv


# ==================== 数据模型 ====================

class CompuMethod(object):
    __slots__ = ('name', 'conv', 'coeffs', 'byte_order', 'unit', 'fmt', 'longid')

    def __init__(self, name):
        self.name = name
        self.conv = None
        self.coeffs = None
        self.byte_order = None
        self.unit = ''
        self.fmt = ''
        self.longid = ''


class LayoutInfo(object):
    __slots__ = ('name', 'value_dtype', 'direction', 'axis_dtypes')

    def __init__(self, name):
        self.name = name
        self.value_dtype = None
        self.direction = 'COLUMN_DIR'
        self.axis_dtypes = {}


class AxisInfo(object):
    __slots__ = ('type_', 'cm', 'ref', 'n', 'lower', 'upper',
                 'fix_values', 'pts_addr', 'pts_dtype')

    def __init__(self):
        self.type_ = None
        self.cm = None
        self.ref = None
        self.n = 0
        self.lower = None
        self.upper = None
        self.fix_values = None
        self.pts_addr = None
        self.pts_dtype = None


class Characteristic(object):
    """标定量对象: VALUE/CURVE/MAP/VAL_BLK/ASCII"""

    __slots__ = ('name', 'longid', 'kind', 'addr', 'dtype', 'cm', 'layout',
                 'lower', 'upper', 'fmt', 'shape', 'axes', 'array_size',
                 'function', 'group')

    def __init__(self, name):
        self.name = name
        self.longid = ''
        self.kind = 'VALUE'
        self.addr = None
        self.dtype = None
        self.cm = None
        self.layout = None
        self.lower = None
        self.upper = None
        self.fmt = ''
        self.shape = (1,)
        self.axes = []
        self.array_size = 1
        self.function = None
        self.group = ''


class Measurement(object):
    __slots__ = ('name', 'longid', 'addr', 'dtype', 'cm', 'lower', 'upper')

    def __init__(self, name):
        self.name = name
        self.longid = ''
        self.addr = None
        self.dtype = None
        self.cm = None
        self.lower = None
        self.upper = None


class GroupNode(object):
    __slots__ = ('name', 'longid', 'members', 'children', 'parent')

    def __init__(self, name):
        self.name = name
        self.longid = ''
        self.members = []
        self.children = []
        self.parent = None


# ==================== 引擎 ====================

class CalibSession(object):

    def __init__(self):
        self.a2l_path = None
        self.hex_path = None
        self.mem = {}
        self.objects = {}
        self.axis_pts = {}
        self.measurements = {}
        self.cms = {}
        self.layouts = {}
        self.functions = {}
        self.groups = {}
        self.var_to_group = {}
        self._orig_bytes = {}
        self.undo_stack = []
        self.redo_stack = []

    # ---------- 加载 ----------

    @classmethod
    def load(cls, a2l_path, hex_path, log=None):
        s = cls()
        s.a2l_path = a2l_path
        s.hex_path = hex_path
        s._parse_a2l(a2l_path, log)
        s.mem = load_intel_hex(hex_path, log)
        s._resolve_objects(log)
        s._snapshot_originals(log)
        return s

    # ---------- A2L 解析 ----------

    def _parse_a2l(self, path, log):
        lines = _read_lines(path)
        blocks, _ = _parse_blocks(lines, need_text=True)
        named = [b for b in blocks if b.get('name')]
        log and log('  A2L 顶层命名块: %d' % len(named))

        for b in named:
            typ = b['type']
            text = b['text']
            tn = _norm_text(text)
            name = b['name']
            if typ == 'COMPU_METHOD':
                cm = CompuMethod(name)
                m = _CONV_RE.search(tn)
                if m:
                    cm.conv = m.group(1)
                m = _COEFFS_RE.search(tn)
                if m:
                    cm.coeffs = tuple(float(x) for x in m.groups())
                m = _BYTE_ORDER_RE.search(tn)
                if m:
                    cm.byte_order = m.group(1)
                m = _UNIT_RE.search(tn)
                if m:
                    cm.unit = m.group(1)
                m = _FORMAT_RE.search(tn)
                if m:
                    cm.fmt = m.group(1)
                m = _LONGID_RE.search(text)
                if m:
                    cm.longid = m.group(1)
                self.cms[name] = cm
            elif typ == 'RECORD_LAYOUT':
                lay = LayoutInfo(name)
                m = _FNC_VALUES_RE.search(tn)
                if m:
                    lay.value_dtype = m.group(1)
                    if m.group(2):
                        lay.direction = m.group(2)
                for am in _AXIS_XYZ_RE.finditer(tn):
                    lay.axis_dtypes[am.group(1)] = am.group(2)
                self.layouts[name] = lay
            elif typ == 'CHARACTERISTIC':
                obj = Characteristic(name)
                obj.addr = self._get_addr(tn)
                obj.layout = self._kw_value(tn, r'Record Layout\s*\*/\s*([A-Za-z_]\w*)')
                obj.cm = self._cm_of(tn)
                ct = self._kw_value(tn, _CHAR_TYPE_RE)
                obj.kind = self._classify(ct)
                m = _LOWER_RE.search(tn)
                if m:
                    obj.lower = float(m.group(1))
                m = _UPPER_RE.search(tn)
                if m:
                    obj.upper = float(m.group(1))
                fm = _FORMAT_RE.search(tn)
                if fm:
                    obj.fmt = fm.group(1)
                lm = _LONGID_RE.search(text)
                if lm:
                    obj.longid = lm.group(1)
                obj.axes = self._parse_axes(tn)
                nm = _NUM_RE.search(tn)
                num = int(nm.group(1)) if nm else None
                obj.shape, obj.array_size = self._calc_shape(obj.kind, obj.axes, num)
                self.objects[name] = obj
            elif typ == 'AXIS_PTS':
                ax = Characteristic(name)
                ax.kind = 'AXIS_PTS'
                ax.addr = self._get_addr(tn)
                ax.layout = self._kw_value(tn, r'Record Layout\s*\*/\s*([A-Za-z_]\w*)')
                ax.cm = self._cm_of(tn)
                m = _LOWER_RE.search(tn)
                if m:
                    ax.lower = float(m.group(1))
                m = _UPPER_RE.search(tn)
                if m:
                    ax.upper = float(m.group(1))
                m = _AXIS_N_RE.search(tn)
                n = int(m.group(1)) if m else 0
                ax.array_size = max(n, 1)
                ax.shape = (max(n, 1),)
                lm = _LONGID_RE.search(text)
                if lm:
                    ax.longid = lm.group(1)
                self.axis_pts[name] = ax
            elif typ == 'MEASUREMENT':
                ms = Measurement(name)
                ms.addr = self._get_addr(tn)
                ms.dtype = self._kw_value(tn, r'Data type\s*\*/\s*([A-Za-z_]\w*)')
                ms.cm = self._cm_of(tn)
                m = _LOWER_RE.search(tn)
                if m:
                    ms.lower = float(m.group(1))
                m = _UPPER_RE.search(tn)
                if m:
                    ms.upper = float(m.group(1))
                lm = _LONGID_RE.search(text)
                if lm:
                    ms.longid = lm.group(1)
                self.measurements[name] = ms
            elif typ == 'FUNCTION':
                members = []
                for sec in ('DEF_CHARACTERISTIC', 'REF_CHARACTERISTIC',
                            'IN_MEASUREMENT', 'OUT_MEASUREMENT'):
                    sm = re.search(r'/begin\s+' + sec + r'(.*?)/end\s+' + sec, tn, re.DOTALL)
                    if sm:
                        members.extend(re.findall(r'[A-Za-z_]\w*', sm.group(1)))
                if members:
                    self.functions.setdefault(name, []).extend(members)
            elif typ == 'GROUP':
                g = GroupNode(name)
                lm = _LONGID_RE.search(text)
                if lm:
                    g.longid = lm.group(1)
                for tag, store in (('REF_CHARACTERISTIC', g.members),
                                   ('REF_MEASUREMENT', g.members),
                                   ('SUB_GROUP', g.children)):
                    sm = re.search(r'/begin\s+' + tag + r'(.*?)/end\s+' + tag, tn, re.DOTALL)
                    if sm:
                        store.extend(re.findall(r'[A-Za-z_]\w*', sm.group(1)))
                self.groups[name] = g

        self._link_groups()

    @staticmethod
    def _kw_value(tn, pattern):
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        m = pattern.search(tn)
        return m.group(1) if m else None

    @staticmethod
    def _cm_of(tn):
        m = _CM_REF_RE.search(tn)
        return m.group(1) if m else None

    @staticmethod
    def _get_addr(tn):
        m = _ECU_ADDR_GET_RE.search(tn)
        return int(m.group(1), 16) if m else None

    @staticmethod
    def _classify(char_type):
        ct = (char_type or '').upper()
        if ct == 'MAP':
            return 'MAP'
        if ct == 'VAL_BLK':
            return 'VAL_BLK'
        if ct == 'ASCII':
            return 'ASCII'
        if ct in ('CURVE', 'STD_AXIS', 'COM_AXIS', 'RES_AXIS', 'CURVE_AXIS',
                  'FIX_AXIS'):
            return 'CURVE'
        return 'VALUE'

    @staticmethod
    def _parse_axes(tn):
        axes = []
        for am in _AXIS_DESCR_RE.finditer(tn):
            seg = am.group(1)
            seg_n = _norm_text(seg)
            ax = AxisInfo()
            m = _AXIS_TYPE_RE.search(seg_n)
            if m:
                ax.type_ = m.group(1).upper()
            m = _CM_REF_RE.search(seg_n)
            if m:
                ax.cm = m.group(1)
            m = _AXIS_PTS_REF_RE.search(seg_n)
            if m:
                ax.ref = m.group(1)
            m = _AXIS_N_RE.search(seg_n)
            if m:
                ax.n = int(m.group(1))
            m = _LOWER_RE.search(seg_n)
            if m:
                ax.lower = float(m.group(1))
            m = _UPPER_RE.search(seg_n)
            if m:
                ax.upper = float(m.group(1))
            fm = _FIX_PAR_RE.search(seg_n)
            if fm:
                offset, dist, number = float(fm.group(2)), float(fm.group(3)), int(fm.group(4))
                ax.fix_values = [offset + i * dist for i in range(number)]
                ax.n = ax.n or number
            axes.append(ax)
        return axes

    @staticmethod
    def _calc_shape(kind, axes, number):
        ns = [ax.n for ax in axes]
        if kind == 'VALUE':
            return (1,), 1
        if kind == 'CURVE':
            n = ns[0] if ns and ns[0] else 1
            return (n,), n
        if kind in ('MAP', 'VAL_BLK'):
            if kind == 'MAP' and len(ns) >= 2 and all(ns[:2]):
                nx, ny = ns[0], ns[1]
                return (nx, ny), nx * ny
            if number and number > 1:
                return (number,), number
            if ns and ns[0]:
                return (ns[0],), ns[0]
            return (1,), 1
        if kind == 'ASCII':
            n = number or (ns[0] if ns and ns[0] else 1)
            return (n,), n
        return (1,), 1

    def _link_groups(self):
        by_name = self.groups
        seen = set()

        def visit(g, parent):
            if id(g) in seen:
                return
            seen.add(id(g))
            g.parent = parent
            for ch in g.children:
                if ch in by_name:
                    visit(by_name[ch], g)

        for g in list(by_name.values()):
            visit(g, None)
        for g in by_name.values():
            for mem in g.members:
                self.var_to_group.setdefault(mem, g.name)

    def _resolve_objects(self, log):
        all_objs = list(self.objects.values()) + list(self.axis_pts.values())
        # 第一遍: 先解析全部对象自身的数据类型/格式
        # (曲线的轴引用可能指向文件中靠后的 AXIS_PTS, 必须两遍解析)
        for obj in all_objs:
            lay = self.layouts.get(obj.layout)
            if lay is not None:
                if getattr(obj, 'kind', '') == 'AXIS_PTS':
                    dt = lay.axis_dtypes.get('X') or lay.value_dtype
                else:
                    dt = lay.value_dtype
                obj.dtype = dt or infer_dtype_from_name(obj.layout)
            else:
                obj.dtype = infer_dtype_from_name(obj.layout)
            if obj.cm and obj.cm in self.cms:
                cm = self.cms[obj.cm]
                if not obj.fmt:
                    obj.fmt = cm.fmt
        # 第二遍: 轴引用联动
        for obj in all_objs:
            for ax in getattr(obj, 'axes', []):
                ref_obj = self.axis_pts.get(ax.ref) if ax.ref else None
                if ref_obj is not None:
                    ax.pts_addr = ref_obj.addr
                    ax.pts_dtype = ref_obj.dtype
                    ax.n = ax.n or ref_obj.array_size
                    ax.cm = ax.cm or ref_obj.cm
                if ax.type_ == 'FIX_AXIS' and ax.fix_values is None and ax.n:
                    ax.fix_values = [float(i) for i in range(ax.n)]

        for func, members in self.functions.items():
            for var in members:
                for pool in (self.objects, self.axis_pts):
                    o = pool.get(var)
                    if o is not None and not o.function:
                        o.function = func
        log and log('  标定量 %d, 轴 %d, 测量 %d, CM %d, LAYOUT %d, GROUP %d' %
                    (len(self.objects), len(self.axis_pts), len(self.measurements),
                     len(self.cms), len(self.layouts), len(self.groups)))

    # ---------- 原始快照 / 脏标记 ----------

    def _raw_region(self, addr, size, count):
        total = size * count
        buf = bytearray(total)
        ok = True
        for i in range(total):
            bv = self.mem.get(addr + i)
            if bv is None:
                ok = False
                break
            buf[i] = bv
        return bytes(buf) if ok else None

    def _obj_raw(self, obj, dtype=None, count=None):
        if not obj.addr:
            return None
        dtype = dtype or obj.dtype
        info = _DT_INFO.get(dtype)
        if not info:
            return None
        count = obj.array_size if count is None else count
        return self._raw_region(obj.addr, info[0], count)

    def _snapshot_originals(self, log):
        n = 0
        for obj in list(self.objects.values()) + list(self.axis_pts.values()):
            raw = self._obj_raw(obj)
            if raw is not None:
                self._orig_bytes[id(obj)] = raw
                n += 1
        log and log('  已快照对象原始值: %d' % n)

    def dirty_cells(self, obj):
        base = self._orig_bytes.get(id(obj))
        if base is None or not obj.addr:
            return set()
        cur = self._obj_raw(obj)
        if cur is None:
            return set()
        size = len(base) // max(obj.array_size, 1)
        out = set()
        for i in range(obj.array_size):
            if base[i * size:(i + 1) * size] != cur[i * size:(i + 1) * size]:
                out.add(i)
        return out

    def is_dirty(self, obj):
        return bool(self.dirty_cells(obj))

    def dirty_objects(self):
        return [o for o in list(self.objects.values()) + list(self.axis_pts.values())
                if self.is_dirty(o)]

    # ---------- 读写值 ----------

    def read_object(self, obj):
        """读标定量当前物理值数组; 缺失字节处为 None"""
        return self._decode(obj, self.mem)

    def read_original(self, obj):
        """读加载时快照的原始物理值数组"""
        base = self._orig_bytes.get(id(obj))
        info = _DT_INFO.get(obj.dtype)
        if base is None or not info or not obj.addr:
            return [None] * obj.array_size
        size = info[0]
        mem = {obj.addr + i: b for i, b in enumerate(base)}
        return self._decode(obj, mem)

    def _decode(self, obj, mem):
        info = _DT_INFO.get(obj.dtype)
        if not info or not obj.addr:
            return [None] * obj.array_size
        size, fmt, is_int = info
        endian = '>' if (self.cm_byte_order(obj) == 'MSB_FIRST') else '<'
        vals = []
        coeffs, _bo = self.cm_coeffs_of(obj)
        for i in range(obj.array_size):
            addr = obj.addr + i * size
            raw = bytes(mem.get(addr + j, 0) for j in range(size))
            missing = any((addr + j) not in mem for j in range(size))
            if missing:
                vals.append(None)
                continue
            rv = struct.unpack(endian + fmt, raw)[0]
            if isinstance(rv, float) and rv != rv:
                vals.append(None)
                continue
            if is_int and coeffs:
                pv = self.raw_to_phys(rv, coeffs)
                vals.append(pv)
            else:
                vals.append(float(rv) if isinstance(rv, (int, float)) else None)
        return vals

    def read_axis(self, obj, axis_index):
        if axis_index >= len(getattr(obj, 'axes', [])):
            return []
        ax = obj.axes[axis_index]
        if ax.type_ == 'FIX_AXIS':
            return list(ax.fix_values or [])
        if not ax.pts_addr:
            return [None] * (ax.n or 0)
        fake = Characteristic('axis')
        fake.addr = ax.pts_addr
        fake.dtype = ax.pts_dtype
        fake.array_size = ax.n
        fake.cm = ax.cm
        return self.read_object(fake)

    @staticmethod
    def raw_to_phys(raw, coeffs):
        a, b, c, d, e, f = coeffs
        den = d * raw * raw + e * raw + f
        if den == 0:
            return None
        A = raw * d - a
        B = raw * e - b
        C = raw * f - c
        if A == 0:
            if B == 0:
                return None
            return -C / B
        disc = B * B - 4 * A * C
        if disc < 0:
            return None
        sq = disc ** 0.5
        p1 = (-B + sq) / (2 * A)
        p2 = (-B - sq) / (2 * A)
        return p1 if abs(p1) <= abs(p2) else p2

    def cm_byte_order(self, obj):
        cm = self.cms.get(obj.cm)
        bo = cm.byte_order if cm else None
        if bo in ('MSB_FIRST', 'BYTE_ORDER_MSB_FIRST', 'MSB_LAST_MOTOROLA'):
            return 'MSB_FIRST'
        return 'MSB_LAST'

    def cm_coeffs_of(self, obj):
        cm = self.cms.get(obj.cm)
        return (cm.coeffs if cm else None), (cm.byte_order if cm else None)

    def check_limits(self, obj, values):
        bad = []
        for i, v in enumerate(values):
            if v is None:
                continue
            if obj.lower is not None and v < obj.lower - 1e-12:
                bad.append((i, v))
            elif obj.upper is not None and v > obj.upper + 1e-12:
                bad.append((i, v))
        return bad

    def write_values(self, obj, values, indices=None, check_limits=True):
        """写入物理值; 返回错误信息列表 [(index, reason)].

        values 两种传法:
        - 与 indices 等长: 逐点对应 (values[k] 写入 indices[k])
        - 全量数组: values[i] 写入第 i 格 (indices 省略时为全部格)
        有实际变更时压入 undo 栈"""
        from core.hex_handler import write_calibration_value
        indices = list(range(obj.array_size)) if indices is None else list(indices)
        if len(values) == len(indices):
            pairs = list(zip(indices, values))
        else:
            pairs = [(i, values[i]) for i in indices if i < len(values)]
        if check_limits:
            bad = self.check_limits(obj, [v for _, v in pairs])
            if bad:
                return ['第%d个值 %s 超出限值 [%s, %s]' %
                        (pairs[bi[0]][0] if bi[0] < len(pairs) else bi[0],
                         format_value(bi[1]), obj.lower, obj.upper)
                        for bi in bad[:5]]
        info = _DT_INFO.get(obj.dtype)
        if not info or not obj.addr:
            return [(indices[0] if indices else 0, '对象无地址或数据类型未知')]
        size = info[0]
        old_bytes = self._obj_raw(obj) or b''
        errors = []
        touched = False
        for i, v in pairs:
            if i >= obj.array_size or v is None:
                continue
            ok, err = write_calibration_value(
                self.mem, obj.addr + i * size, v, obj.dtype,
                *self._write_args(obj))
            if ok:
                touched = True
            else:
                errors.append((i, err))
        if touched:
            new_bytes = self._obj_raw(obj) or b''
            if new_bytes != old_bytes:
                self.undo_stack.append(_EditCommand(
                    obj.name, obj.addr, size, old_bytes, new_bytes))
                self.redo_stack.clear()
        return errors

    def restore_object(self, obj):
        """整对象还原为加载时的原始值 (可被 undo)"""
        base = self._orig_bytes.get(id(obj))
        info = _DT_INFO.get(obj.dtype)
        if base is None or not obj.addr or not info:
            return False
        size = info[0]
        cur = self._obj_raw(obj)
        if cur is None or cur == base:
            return False
        for i, bv in enumerate(base):
            self.mem[obj.addr + i] = bv
        self.undo_stack.append(_EditCommand(
            obj.name, obj.addr, size, cur, base))
        self.redo_stack.clear()
        return True

    def _write_args(self, obj):
        coeffs, byte_order = self.cm_coeffs_of(obj)
        return (coeffs, byte_order)

    def unit_of(self, obj):
        cm = self.cms.get(obj.cm)
        return cm.unit if cm else ''

    def storage_direction(self, obj):
        lay = self.layouts.get(getattr(obj, 'layout', None))
        return lay.direction if lay else 'COLUMN_DIR'

    def grid_to_flat(self, obj, r, c):
        """网格坐标 -> 内存平坦索引.
        MAP: shape=(nx,ny), 行=r(Y) 列=c(X);
        COLUMN_DIR 为 X 外层/Y 内层 (k=c*ny+r), ROW_DIR 反之"""
        shape = getattr(obj, 'shape', (1,))
        if len(shape) == 2:
            nx, ny = shape
            if self.storage_direction(obj) == 'ROW_DIR':
                return r * nx + c
            return c * ny + r
        return r

    def flat_to_grid(self, obj, k):
        """内存平坦索引 -> 网格坐标 (r, c)"""
        shape = getattr(obj, 'shape', (1,))
        if len(shape) == 2:
            nx, ny = shape
            if self.storage_direction(obj) == 'ROW_DIR':
                return (k // nx, k % nx)
            return (k % ny, k // ny)
        return (k, 0)

    # ---------- Undo / Redo ----------

    def undo(self):
        if not self.undo_stack:
            return False
        cmd = self.undo_stack.pop()
        cmd.revert(self.mem)
        self.redo_stack.append(cmd)
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        cmd = self.redo_stack.pop()
        cmd.apply(self.mem)
        self.undo_stack.append(cmd)
        return True

    # ---------- 保存 ----------

    def save_hex(self, path):
        save_intel_hex(path, self.mem)

    # ---------- DCM 导出 ----------

    def _axis_unit(self, obj, i):
        ax = obj.axes[i]
        cm = self.cms.get(ax.cm)
        return (cm.unit if cm else '') or ''

    def export_dcm(self, path, only_dirty=False, log=None):
        """把当前会话标定值导出为 DCM (KONSERVIERUNG_FORMAT 2.0).
        返回 {'exported': n, 'skipped': n, 'skipped_names': [...]}"""
        from utils.logger import timestamp

        def num(v):
            return '%.10g' % v

        def dstr(s):
            return '"%s"' % (s or '').replace('"', "'")

        def chunk(vals, n=8):
            for i in range(0, len(vals), n):
                yield '  WERT ' + ' '.join(vals[i:i + n])

        entries = []
        used_funcs = set()
        skipped_names = []
        pool = sorted(list(self.objects.values()) + list(self.axis_pts.values()),
                      key=lambda o: o.name)
        for obj in pool:
            if only_dirty and not self.is_dirty(obj):
                continue
            vals = self.read_object(obj)
            if obj.kind == 'AXIS_PTS':
                if any(v is None for v in vals):
                    skipped_names.append(obj.name)
                    continue
                st = [num(v) for v in vals]
                entries.append(['STUETZSTELLENVERTEILUNG %s X' % obj.name,
                                '  LANGNAME %s' % dstr(obj.longid)])
                if obj.function:
                    entries[-1].append('  FUNKTION %s' % obj.function)
                    used_funcs.add(obj.function)
                cm = self.cms.get(obj.cm)
                if cm and cm.unit:
                    entries[-1].append('  EINHEIT_X %s' % dstr(cm.unit))
                entries[-1].append('  ST/X ' + ' '.join(st))
                entries[-1].append('END')
                continue
            if all(v is None for v in vals):
                skipped_names.append(obj.name)
                continue
            fn = '  FUNKTION %s' % obj.function if obj.function else None
            if obj.function:
                used_funcs.add(obj.function)
            unit = self.unit_of(obj)

            def common():
                head = ['  LANGNAME %s' % dstr(obj.longid)]
                if fn:
                    head.append(fn)
                if unit:
                    head.append('  EINHEIT_W %s' % dstr(unit))
                return head

            if obj.kind == 'VALUE':
                if vals[0] is None:
                    skipped_names.append(obj.name)
                    continue
                entries.append(['FESTWERT %s' % obj.name] + common() +
                               ['  WERT ' + num(vals[0]), 'END'])
            elif obj.kind == 'VAL_BLK':
                if any(v is None for v in vals):
                    skipped_names.append(obj.name)
                    continue
                entries.append(['FESTWERTEBLOCK %s' % obj.name] + common() +
                               list(chunk([num(v) for v in vals])) + ['END'])
            elif obj.kind == 'CURVE':
                xs = self.read_axis(obj, 0)
                if not xs or any(v is None for v in xs) or any(v is None for v in vals):
                    skipped_names.append(obj.name)
                    continue
                e = ['GRUPPENKENNLINIE %s X' % obj.name] + common()
                e.append('  EINHEIT_X %s' % dstr(self._axis_unit(obj, 0)))
                e.append('  ST/X ' + ' '.join(num(v) for v in xs))
                e.extend(chunk([num(v) for v in vals]))
                e.append('END')
                entries.append(e)
            elif obj.kind in ('MAP',):
                if len(obj.shape) != 2:
                    skipped_names.append(obj.name)
                    continue
                nx, ny = obj.shape
                xs = self.read_axis(obj, 0)
                ys = self.read_axis(obj, 1)
                if (not xs or not ys or any(v is None for v in xs + ys)
                        or any(v is None for v in vals)):
                    skipped_names.append(obj.name)
                    continue
                e = ['GRUPPENKENNFELD %s X Y' % obj.name] + common()
                e.append('  EINHEIT_X %s' % dstr(self._axis_unit(obj, 0)))
                e.append('  EINHEIT_Y %s' % dstr(self._axis_unit(obj, 1)))
                e.append('  ST/X ' + ' '.join(num(v) for v in xs))
                e.append('  ST/Y ' + ' '.join(num(v) for v in ys))
                # DCM 的 WERT 按 ST/Y 逐行存放 (Y 外层, X 内层); 每行都带 WERT 关键字
                for j in range(ny):
                    row = [num(vals[self.grid_to_flat(obj, j, i)]) for i in range(nx)]
                    e.append('  WERT ' + ' '.join(row))
                e.append('END')
                entries.append(e)
            else:
                skipped_names.append(obj.name)

        lines = ['KONSERVIERUNG_FORMAT 2.0', '',
                 '* A2L Toolbox 在线标定数据集',
                 '* Datum %s' % timestamp(),
                 '* A2L: %s' % self.a2l_path,
                 '* HEX: %s' % self.hex_path, '']
        if used_funcs:
            lines.append('FUNKTIONEN')
            for f in sorted(used_funcs):
                lines.append('  %s' % f)
            lines.append('END')
            lines.append('')
        for e in entries:
            lines.extend(e)
            lines.append('')
        with open(path, 'w', encoding='utf-8', newline='\r\n') as f:
            f.write('\n'.join(lines) + '\n')
        log and log('  DCM 导出: %d 个对象 (跳过 %d)' % (len(entries), len(skipped_names)))
        return {'exported': len(entries), 'skipped': len(skipped_names),
                'skipped_names': skipped_names}

    # ---------- DCM 导入 ----------

    def _apply_batch(self, f):
        """f() 期间压入的 undo 命令合并为单个撤销单元, 返回 f() 的返回值"""
        mark = len(self.undo_stack)
        result = f()
        cmds = self.undo_stack[mark:]
        del self.undo_stack[mark:]
        if cmds:
            self.undo_stack.append(cmds[0] if len(cmds) == 1
                                   else _BatchCommand(cmds))
            self.redo_stack.clear()
        return result

    def apply_dcm(self, path, log=None):
        """把 DCM 数据集应用到当前会话 (整体一个 Undo 单元).
        返回 {'applied': n, 'skipped': n, 'errors': [(name, msg)], 'missing': n}"""
        from core.dcm_handler import parse_dcm
        dcm_objs = parse_dcm(path, log)
        missing = applied = skipped = 0
        errors = []

        def do_apply():
            nonlocal missing, applied, skipped
            for name, o in dcm_objs.items():
                tgt = self.objects.get(name) or self.axis_pts.get(name)
                kind = o['kind']
                if tgt is None:
                    # 曲线/MAP 的 DCM 名对应标定量; 轴数据随主对象应用
                    missing += 1
                    continue
                if not tgt.addr:
                    errors.append((name, 'ECU 地址为 0x0000'))
                    continue
                try:
                    if kind in ('FESTWERT', 'FESTWERTEBLOCK'):
                        vals = list(o['values'])
                        if len(vals) != tgt.array_size:
                            errors.append((name, '值个数 %d != 对象元素 %d'
                                           % (len(vals), tgt.array_size)))
                            continue
                    elif kind in ('GRUPPENKENNLINIE', 'FESTKENNLINIE'):
                        vals = list(o['values'])
                        if len(vals) != tgt.array_size:
                            errors.append((name, '值个数 %d != %d'
                                           % (len(vals), tgt.array_size)))
                            continue
                        if o['xs'] and getattr(tgt, 'axes', []):
                            self._apply_axis(tgt, 0, o['xs'], errors)
                    elif kind == 'GRUPPENKENNFELD':
                        vals = list(o['values'])
                        nx, ny = tgt.shape if len(tgt.shape) == 2 else (tgt.array_size, 1)
                        if len(o['xs']) != nx or len(o['ys']) != ny \
                                or len(vals) != nx * ny:
                            errors.append((name, '维度 %dx%d 与 DCM %dx%d 不符'
                                           % (nx, ny, len(o['xs']), len(o['ys']))))
                            continue
                        # DCM 线性顺序为 Y 外层/X 内层, 按存储方向散射到内存平坦索引
                        ordered = [None] * (nx * ny)
                        for j in range(ny):
                            for i in range(nx):
                                ordered[self.grid_to_flat(tgt, j, i)] = \
                                    o['values'][j * nx + i]
                        vals = ordered
                        if getattr(tgt, 'axes', []):
                            self._apply_axis(tgt, 0, o['xs'], errors)
                            self._apply_axis(tgt, 1, o['ys'], errors)
                    elif kind == 'STUETZSTELLENVERTEILUNG':
                        vals = list(o['values'] or o['xs'])
                        if len(vals) != tgt.array_size:
                            errors.append((name, '轴点数 %d != %d'
                                           % (len(vals), tgt.array_size)))
                            continue
                    else:
                        skipped += 1
                        continue
                    errs = self.write_values(tgt, vals, check_limits=True)
                    if errs:
                        errors.append((name, str(errs[0][1]) if isinstance(errs[0], tuple)
                                       else str(errs[0])))
                    else:
                        applied += 1
                except Exception as ex:
                    errors.append((name, str(ex)))
            return {'applied': applied, 'skipped': skipped,
                    'errors': errors, 'missing': missing}

        return self._apply_batch(do_apply)

    def _apply_axis(self, obj, axis_index, values, errors):
        """把 DCM 的 ST/X-ST/Y 应用到曲线/MAP 关联的 AXIS_PTS 对象"""
        ax = obj.axes[axis_index]
        if ax.type_ != 'COM_AXIS' or not ax.ref:
            return
        tgt = self.axis_pts.get(ax.ref)
        if tgt is None or not tgt.addr:
            return
        vals = list(values)
        if len(vals) != tgt.array_size:
            errors.append((ax.ref, '轴点数 %d != %d' % (len(vals), tgt.array_size)))
            return
        errs = self.write_values(tgt, vals, check_limits=True)
        if errs:
            errors.append((ax.ref, str(errs[0][1]) if isinstance(errs[0], tuple)
                           else str(errs[0])))

    # ---------- HEX 对比 ----------

    def compare_hex(self, path, log=None):
        """当前内存与另一 HEX 文件逐字节对比.
        返回 {'diff_bytes', 'objects': [(name, kind, changed_cells, total)],
              'unknown_bytes', 'total_self', 'total_other'}"""
        import bisect
        other = load_intel_hex(path, log)
        all_addrs = set(self.mem.keys()) | set(other.keys())
        diff_addrs = sorted(a for a in all_addrs if self.mem.get(a) != other.get(a))
        ranges = []
        for obj in list(self.objects.values()) + list(self.axis_pts.values()):
            info = _DT_INFO.get(obj.dtype)
            if not info or not obj.addr:
                continue
            ranges.append((obj.addr, obj.addr + info[0] * obj.array_size - 1, obj))
        ranges.sort()
        starts = [r[0] for r in ranges]
        touched = {}
        unknown = 0
        for a in diff_addrs:
            i = bisect.bisect_right(starts, a) - 1
            if i >= 0 and a <= ranges[i][1]:
                obj = ranges[i][2]
                touched.setdefault(obj.name, [obj, set()])[1].add(a)
            else:
                unknown += 1
        obj_stats = []
        for name, (obj, addrs) in touched.items():
            size = _DT_INFO[obj.dtype][0]
            cells = {(a - obj.addr) // size for a in addrs if a >= obj.addr}
            obj_stats.append((name, getattr(obj, 'kind', ''),
                              len(cells), obj.array_size))
        obj_stats.sort()
        log and log('  HEX 对比: 差异字节 %d, 涉及对象 %d, 对象外差异 %d'
                    % (len(diff_addrs), len(obj_stats), unknown))
        return {'diff_bytes': len(diff_addrs), 'objects': obj_stats,
                'unknown_bytes': unknown,
                'total_self': len(self.mem), 'total_other': len(other)}


class _EditCommand(object):
    __slots__ = ('obj_name', 'addr', 'size', 'old_bytes', 'new_bytes')

    def __init__(self, obj_name, addr, size, old_bytes, new_bytes):
        self.obj_name = obj_name
        self.addr = addr
        self.size = size
        self.old_bytes = old_bytes
        self.new_bytes = new_bytes

    def apply(self, mem):
        for i, bv in enumerate(self.new_bytes):
            mem[self.addr + i] = bv

    def revert(self, mem):
        for i, bv in enumerate(self.old_bytes):
            mem[self.addr + i] = bv


class _BatchCommand(object):
    """多个编辑命令的复合撤销单元 (如 DCM 导入)"""

    __slots__ = ('obj_name', 'cmds')

    def __init__(self, cmds):
        self.cmds = cmds
        self.obj_name = 'batch(%d)' % len(cmds)

    def apply(self, mem):
        for c in self.cmds:
            c.apply(mem)

    def revert(self, mem):
        for c in reversed(self.cmds):
            c.revert(mem)
