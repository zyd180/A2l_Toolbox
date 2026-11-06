#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模型版本同步模块 - 将新版模型 A2L 的对象同步进整车 A2L"""

import re
import bisect
import shutil
import time
from collections import Counter
from pathlib import Path

from .map_parser import map_owner


# ==================== 常量定义 ====================

SYNC_TOP_TYPES = {'RECORD_LAYOUT', 'COMPU_METHOD', 'CHARACTERISTIC', 'AXIS_PTS',
                  'MEASUREMENT', 'GROUP', 'FUNCTION'}

_IDENT = r'[A-Za-z_][A-Za-z0-9_]*'
_BEGIN_RE = re.compile(r'/begin\s+(' + _IDENT + r')')
_END_RE = re.compile(r'/end\s+(' + _IDENT + r')')
_ADDR_CHAR_RE = re.compile(r'(ECU Address\s*\*/\s*)0x[0-9A-Fa-f]+')
_ADDR_MEAS_RE = re.compile(r'(ECU_ADDRESS\s+)0x[0-9A-Fa-f]+')
_ADDR_CHAR_GET_RE = re.compile(r'ECU Address\s*\*/\s*(0x[0-9A-Fa-f]+)')
_ADDR_MEAS_GET_RE = re.compile(r'ECU_ADDRESS\s+(0x[0-9A-Fa-f]+)')
# 地址行有两种合法写法: 注释形式 "/* ECU Address */ 0x..." (Simulink 生成)
# 与关键字形式 "ECU_ADDRESS 0x..." (ASAP2 标准, 部分工具输出)。
# 只认其中一种会让另一侧的整车/模型 A2L 在同步时丢失真实地址 (被 0x0000 覆盖),
# 故读写两侧都同时接受两种写法。
_CM_REF_RE = re.compile(r'Conversion [Mm]ethod\s*\*/\s*([A-Za-z_][A-Za-z0-9_]*)')


# 地址行的 (回写用, 取名前缀) 与 (读取用) 模式, 按优先级排列
_ADDR_SUB_ORDER = {
    'MEASUREMENT': (_ADDR_MEAS_RE, _ADDR_CHAR_RE),
    'CHARACTERISTIC': (_ADDR_CHAR_RE, _ADDR_MEAS_RE),
    'AXIS_PTS': (_ADDR_CHAR_RE, _ADDR_MEAS_RE),
}
_ADDR_GET_ORDER = {
    'MEASUREMENT': (_ADDR_MEAS_GET_RE, _ADDR_CHAR_GET_RE),
    'CHARACTERISTIC': (_ADDR_CHAR_GET_RE, _ADDR_MEAS_GET_RE),
    'AXIS_PTS': (_ADDR_CHAR_GET_RE, _ADDR_MEAS_GET_RE),
}


# ==================== 工具函数 ====================

def _decode_mixed(b):
    """字节级分段救援解码, 处理行内混合编码 (UTF-8 主体 + GBK 标点/中文 + Latin-1 符号).

    规则:
    - ASCII 游程直通
    - 合法 UTF-8 多字节序列按 UTF-8 解 (保住真中文)
    - 其余字节按 GBK 双字节解 (如 GBK 的 （℃） 不再被误拼成 棩 这类伪 UTF-8 字符)
    - 歧义保护: GBK 第二字节为字母/数字时拆开按单字节解 (保护 °C/µs 等单位,
      避免 Latin-1 的 0xB0+'C' 被吞成一个 CJK 字)
    - 兜底 cp1252 单字节, 永不丢字节"""
    out = []
    i, n = 0, len(b)
    while i < n:
        c = b[i]
        if c < 0x80:
            j = i
            while j < n and b[j] < 0x80:
                j += 1
            out.append(b[i:j].decode('ascii'))
            i = j
            continue
        i0 = i
        for ln in (2, 3, 4):
            seq = b[i:i + ln]
            if len(seq) < ln:
                break
            if ln == 2:
                # 2 字节 UTF-8 (U+0080-U+07FF: 拉丁扩展/希腊/西里尔) 的字节区间
                # 与 GBK 汉字首字节区 (C2-F7) 重叠, 如 GBK"预"(D4A4) 恰是合法
                # UTF-8 双字节 (Ԥ). A2L 里 2 字节 UTF-8 几乎不出现而 GBK 汉字常见:
                # 该对同时是合法 GBK 且解出常用汉字时, 优先按 GBK 解
                try:
                    g = seq.decode('gbk')
                except UnicodeDecodeError:
                    g = None
                if g is not None and '\u4e00' <= g <= '\u9fff':
                    out.append(g)
                    i += ln
                    break
            try:
                out.append(seq.decode('utf-8'))
                i += ln
                break
            except UnicodeDecodeError:
                continue
        if i == i0:
            # 没有任何多字节序列成功 (含剩余字节不足的情况): GBK 双字节尝试,
            # 但第二字节为字母/数字时拆开 (保护 °C/µs 等单位), 兜底 cp1252 单字节
            nxt = b[i + 1] if i + 1 < n else 0
            if 0x81 <= c <= 0xFE and nxt >= 0x80:
                try:
                    out.append(b[i:i + 2].decode('gbk'))
                    i += 2
                except UnicodeDecodeError:
                    out.append(b[i:i + 1].decode('cp1252', errors='replace'))
                    i += 1
            else:
                out.append(b[i:i + 1].decode('cp1252', errors='replace'))
                i += 1
    return ''.join(out)


def _gbk_eats_ascii(b):
    """模拟 GBK 配对扫描: 若存在双字节对的第二字节是 ASCII 数字/字母
    (即 GBK 解码会把 '°C' 的 C、'µs' 的 s 吞进汉字对), 返回 True"""
    i, n = 0, len(b)
    while i < n:
        c = b[i]
        if c < 0x80:
            i += 1
            continue
        if 0x81 <= c <= 0xFE and i + 1 < n and b[i + 1] >= 0x40:
            if 0x30 <= b[i + 1] <= 0x7A:
                return True
            i += 2
            continue
        i += 1
    return False


def _read_lines(path):
    """按行读取 ASAP2/DCM 文本文件. 失败行的判定:
    - 整行 GBK 可解且不吞 ASCII 字母/数字 -> 按 GBK (A2L 中文/全角标点的主流形态)
    - 否则字节级分段救援 _decode_mixed (行内 UTF-8 主体 + 少量异类字节的混合行)
    读取端还原为正确 unicode: GUI 显示不乱码, 导出产物为合法 UTF-8."""
    with open(path, 'rb') as f:
        raw_lines = f.readlines()
    out = []
    for ln in raw_lines:
        try:
            out.append(ln.decode('utf-8'))
            continue
        except UnicodeDecodeError:
            pass
        try:
            if not _gbk_eats_ascii(ln):
                out.append(ln.decode('gbk'))
                continue
        except UnicodeDecodeError:
            pass
        out.append(_decode_mixed(ln))
    return out


def _read_lines_lf(path):
    """同 _read_lines, 但行尾归一化为 \\n (供合并/地址映射等按行回写的场景使用,
    保持与文本模式读取一致的行尾, 避免写出 \\r\\r\\n)"""
    return [l.replace('\r\n', '\n').replace('\r', '\n') for l in _read_lines(path)]


def _comment_stripped(lines):
    """去掉 /* */ 注释(支持跨行), 用于标记解析"""
    out = []
    in_comment = False
    for raw in lines:
        s = []
        i = 0
        n = len(raw)
        while i < n:
            if in_comment:
                j = raw.find('*/', i)
                if j < 0:
                    i = n
                else:
                    in_comment = False
                    i = j + 2
            else:
                j = raw.find('/*', i)
                if j < 0:
                    s.append(raw[i:])
                    i = n
                else:
                    s.append(raw[i:j])
                    in_comment = True
                    i = j + 2
        out.append(''.join(s))
    return out


def _events_of(s):
    ev, pos = [], 0
    while True:
        mb = _BEGIN_RE.search(s, pos)
        me = _END_RE.search(s, pos)
        if not mb and not me:
            break
        if mb and (not me or mb.start() < me.start()):
            ev.append(('B', mb.group(1)))
            pos = mb.end()
        else:
            ev.append(('E', me.group(1)))
            pos = me.end()
    return ev


def _parse_blocks(lines, need_text=True):
    """解析 MODULE 直接子块. 返回 (blocks, module_end),
    blocks: [{type,name,longid,start,end,text}], start/end 为 0-based 行号"""
    stripped = _comment_stripped(lines)
    blocks = []
    stack = []
    module_depth = None
    pending = None
    module_end = None

    for idx, s in enumerate(stripped):
        for kind, tok in _events_of(s):
            if kind == 'B':
                stack.append((tok, idx))
                if tok == 'MODULE':
                    module_depth = len(stack)
                elif module_depth is not None and len(stack) == module_depth + 1 \
                        and tok in SYNC_TOP_TYPES:
                    pending = {'type': tok, 'start': idx, 'name': None}
            else:
                if stack and stack[-1][0] == tok:
                    stack.pop()
                if tok == 'MODULE':
                    module_end = idx
        if pending is not None and pending['name'] is None:
            t = re.sub(r'/begin\s+' + _IDENT, ' ', s, count=1)
            t = re.sub(r'"[^"]*"', ' ', t)
            m = re.search(_IDENT, t)
            if m:
                pending['name'] = m.group(0)
                blocks.append(pending)
                pending = None

    if need_text:
        open_starts = {b['start']: b for b in blocks}
        stack2 = []
        for idx, s in enumerate(stripped):
            for kind, tok in _events_of(s):
                if kind == 'B':
                    stack2.append((tok, idx))
                else:
                    if stack2 and stack2[-1][0] == tok:
                        bt, bs = stack2.pop()
                        if bs in open_starts and 'end' not in open_starts[bs]:
                            open_starts[bs]['end'] = idx
        for b in blocks:
            b.setdefault('end', len(lines) - 1)
            text = ''.join(lines[b['start']:b['end'] + 1])
            b['text'] = text
            m = re.search(r'"((?:[^"\\]|\\.)*)"', text)
            b['longid'] = m.group(1) if m else ''
    return blocks, module_end


def _get_addr(b):
    """读对象当前 ECU 地址; 注释式与关键字式两种写法都认"""
    for pat in _ADDR_GET_ORDER.get(b['type'], (_ADDR_CHAR_GET_RE, _ADDR_MEAS_GET_RE)):
        m = pat.search(b['text'])
        if m:
            return m.group(1)
    return None


def _merge_addr(src_text, typ, tgt_addr):
    """把目标真实地址写回源块文本(源为 0x0000 占位符时); 两种写法都支持"""
    if not tgt_addr or tgt_addr == '0x0000':
        return src_text, False
    for pat in _ADDR_SUB_ORDER.get(typ, ()):
        new, n = pat.subn(r'\g<1>' + tgt_addr, src_text, count=1)
        if n:
            return new, True
    return src_text, False


def _norm_for_compare(text):
    """归一化后比较: 去掉 ECU 地址、长标识字符串、多余空白"""
    t = re.sub(r'0x[0-9A-Fa-f]+', ' ', text)
    t = re.sub(r'"[^"]*"', ' ', t)
    t = re.sub(r'[ \t\r\n]+', ' ', t)
    return t.strip()


# 生成器残留的地址标注 /* @ECU_Address@Name@ */: 其中的 Name 与同一块的
# /* Name */ 完全重复 (实测 44535 个块, 0 例不同), 且它是 C 风格注释,
# ASAP2/INCA 解析器一律跳过 -> 纯冗余。合并产物实测 40249 条 (约 1.7MB);
# 同步时若不剥除, 每同步一批模型都会往整车 A2L 里灌进上万条 (实测 9718 条)。
_ADDR_ANN_RE = re.compile(r'[ \t]*/\*[ \t]*@ECU_Address@[A-Za-z_]\w*@[ \t]*\*/')


def strip_addr_annotation(text):
    """剥除生成器残留的地址标注注释, 返回清理后的文本 (无该标注时原样返回)"""
    if '@ECU_Address@' not in text:
        return text
    return _ADDR_ANN_RE.sub('', text)


_OBJ_TYPES = ('CHARACTERISTIC', 'MEASUREMENT', 'AXIS_PTS')


def _source_model_name(lines, src_path):
    """源 A2L 的模型名: 取头部 "Code generation for model \"X\"" 注释.

    取不到返回 None (调用方自行决定退回文件名还是退回 CM 前缀推导), 因为
    清理逻辑的模型前缀必须与文件里实际的 CM 前缀一致, 直接拿文件名顶替会判错归属。
    """
    head = ''.join(lines[:80])
    m = re.search(r'Code generation for model\s+"([^"]+)"', head)
    return m.group(1) if m else None


def _foreign_ref_keys(src_blocks, tgt_blocks, owner_map, model):
    """找出"源文件声明了、但不由它定义"的对象.

    判据与合并里的去重一致: MAP 符号行的定义模块才是定义方。若定义方是别的模型,
    而目标 A2L 已有该对象, 本文件的声明只是引用, 不能覆盖定义方的定义
    (引用方常带 uint8 兜底 255 的宽限值, 覆盖会把标定界面的上下限放宽)。
    返回 [(type, name, 定义方)]
    """
    if not owner_map:
        return []
    tgt_keys = {(b['type'], b['name']) for b in tgt_blocks}
    out = []
    for b in src_blocks:
        if b['type'] not in _OBJ_TYPES:
            continue
        own = map_owner(owner_map, b['name'])
        if own and own.lower() != model.lower() and (b['type'], b['name']) in tgt_keys:
            out.append((b['type'], b['name'], own))
    return out


# ==================== 核心同步逻辑 ====================

def _merge_blocks(src_blocks, tgt_lines, tgt_blocks, module_end, skip_ref=None):
    """将源块合并进目标: 同名块原位更新(保留地址), FUNCTION 同名整体更新,
    缺失的新增块直接插入目标中该模型原有区域之后 (GROUP 不同步不保留).

    skip_ref: 需要按"引用方声明"跳过的 (type, name) 集合 —— 这些对象在 MAP 里由
    别的模型定义, 而目标 A2L 已有该对象, 因此不能让本模型的引用式声明覆盖定义方的定义.
    返回 (新行列表, 统计dict)"""
    skip_ref = skip_ref or set()
    tgt_by_key = {}
    for b in tgt_blocks:
        tgt_by_key.setdefault((b['type'], b['name']), []).append(b)

    replacements = []
    additions = []
    kept_same = []
    skipped_ref = []

    for sb in src_blocks:
        typ, name = sb['type'], sb['name']
        if typ == 'GROUP':
            # GROUP 不再同步/保留, 直接跳过
            continue
        if (typ, name) in skip_ref:
            skipped_ref.append((typ, name))
            continue
        if typ == 'FUNCTION':
            # 同名 FUNCTION 以新版为准整体更新, 目标没有则新增
            cands = tgt_by_key.get(('FUNCTION', name), [])
            if cands:
                for tb in cands:
                    replacements.append((tb, sb['text'], 'FUNCTION 更新'))
            else:
                additions.append((sb, sb['text']))
            continue

        cands = tgt_by_key.get((typ, name), [])
        if not cands:
            additions.append((sb, sb['text']))
            continue
        if typ == 'RECORD_LAYOUT':
            for tb in cands:
                replacements.append((tb, sb['text'], 'RECORD_LAYOUT 更新'))
            continue
        if typ == 'COMPU_METHOD':
            for tb in cands:
                replacements.append((tb, sb['text'], 'COMPU_METHOD 更新'))
            continue

        # CHARACTERISTIC / AXIS_PTS / MEASUREMENT
        if len(cands) == 1:
            # 目标仅一个同名块 -> 以新版为准更新, 保留原有真实地址
            tb = cands[0]
            new_text, addr_kept = _merge_addr(sb['text'], typ, _get_addr(tb))
            replacements.append((tb, new_text,
                                 ('更新, 保留原地址 %s' % _get_addr(tb)) if addr_kept
                                 else '更新'))
            continue
        # 多个同名块(来自多个模型): 只更新与源内容(地址/长标识归一化后)一致者
        src_norm = _norm_for_compare(sb['text'])
        matching = [tb for tb in cands if _norm_for_compare(tb['text']) == src_norm]
        if matching:
            for tb in matching:
                new_text, addr_kept = _merge_addr(sb['text'], typ, _get_addr(tb))
                replacements.append((tb, new_text,
                                     ('同名多处, 更新等效副本, 保留地址 %s' % _get_addr(tb))
                                     if addr_kept else '同名多处, 更新等效副本'))
        else:
            kept_same.append((typ, name,
                              '目标存在 %d 处同名块且内容均有差异, 为避免误改其他模型, 全部保持不变'
                              % len(cands)))

    seen = set()
    for tb, new_text, reason in replacements:
        if id(tb) in seen:
            raise RuntimeError('重复替换: %s %s' % (tb['type'], tb['name']))
        seen.add(id(tb))

    order = {'COMPU_METHOD': 0, 'AXIS_PTS': 1, 'CHARACTERISTIC': 2,
             'MEASUREMENT': 3, 'FUNCTION': 4}
    additions.sort(key=lambda x: (order.get(x[0]['type'], 9), x[0]['name']))

    # 新增块插入点: 目标中模型原有数据区域之后 (原位插入, 不再另起标记区段);
    # 模型在目标中无已有对象时退回 /end MODULE 之前
    insert_at = module_end
    if additions:
        model = None
        for b in src_blocks:
            if b['type'] == 'COMPU_METHOD' and '_CM_' in b['name']:
                model = b['name'].split('_CM_')[0]
                break
        if model:
            cm_prefix = model + '_CM_'
            last_end = None
            for b in tgt_blocks:
                if b['type'] == 'COMPU_METHOD':
                    belong = b['name'].startswith(cm_prefix)
                elif b['type'] in ('CHARACTERISTIC', 'AXIS_PTS', 'MEASUREMENT'):
                    m = _CM_REF_RE.search(b['text'])
                    belong = bool(m and m.group(1).startswith(cm_prefix))
                else:
                    belong = False
                if belong and (last_end is None or b['end'] > last_end):
                    last_end = b['end']
            if last_end is not None:
                insert_at = last_end + 1

    nl = '\r\n' if any(l.endswith('\r\n') for l in tgt_lines[:100]) else '\n'
    # 新增块文本为多行整体, 必须拆成单行元素 (与替换块一致),
    # 否则后续按行号定位/块范围比较会错位
    add_texts = []
    for _, t in additions:
        if not t.endswith('\n'):
            t += nl
        add_texts.extend(t.replace('\r\n', '\n').replace('\n', nl).splitlines(True))

    repl_map = {}
    for tb, new_text, reason in replacements:
        if not new_text.endswith('\n'):
            new_text += nl
        new_text = new_text.replace('\r\n', '\n').replace('\n', nl)
        repl_map[tb['start']] = (tb['end'], new_text.splitlines(True))

    out = []
    i = 0
    n = len(tgt_lines)
    while i < n:
        if i == insert_at and add_texts:
            out.append(nl)
            out.extend(add_texts)
        if i in repl_map:
            end, new_lines = repl_map[i]
            out.extend(new_lines)
            i = end + 1
        else:
            out.append(tgt_lines[i])
            i += 1

    stats = {'replacements': replacements, 'additions': additions,
             'kept_same': kept_same, 'insert_at': insert_at,
             'skipped_ref': skipped_ref}
    return out, stats


def _purge_blocks(lines, src_blocks, model=None, owner_map=None):
    """删除旧版模型中已不存在的对象.
    归属判定: 有 MAP 时以"定义该符号的模块"为准 (与合并去重同一判据); 没有归属信息时
    退回 CM 名称前缀 / 块内引用本模型 CM. 只按 CM 前缀判会漏删: 模型内部子系统改名后
    (如 RESTQ_ResTqReq_CM_* -> VCUTqReqMng_CM_*), 老对象挂的还是旧前缀, 一个也判不到.
    本模型的 GROUP 块不再保留, 清理时全部删除.
    删除前检查对象名在待删块之外是否仍被引用, 有残留引用则保留;
    模型自身 FUNCTION 块内的引用不阻止删除 (GROUP 则排除全部 FUNCTION 块内的
    同名出现, 避免与 FUNCTION 重名误判), 并同步清理其引用行.
    只被待删对象引用的 COMPU_METHOD 一并清理 (否则留下孤儿 CM).
    返回 (新行列表, 统计dict)"""
    src_names = {}
    for b in src_blocks:
        if not b.get('name'):
            continue
        src_names.setdefault(b['type'], set()).add(b['name'])

    cm_prefix = None
    for b in src_blocks:
        if b['type'] == 'COMPU_METHOD' and '_CM_' in b['name']:
            cm_prefix = b['name'].split('_CM_')[0] + '_CM_'
            break
    model = model or (cm_prefix[:-len('_CM_')] if cm_prefix else None)
    if not model:
        return lines, {'deleted': [], 'kept_warn': [],
                       'note': '源文件未识别出模型名, 跳过清理'}

    tgt_blocks, _ = _parse_blocks(lines, need_text=True)
    tgt_blocks = [b for b in tgt_blocks if b.get('name')]

    # ---- 第一遍: 对象. 归属优先用 MAP 定义方, 无归属信息时退回 CM 前缀 ----
    candidates = []
    cand_keys = set()
    stale_families = set()      # 遗留对象所属的旧命名家族 (CM 前缀根), 供 GROUP 判定
    for b in tgt_blocks:
        typ, name = b['type'], b['name']
        if typ not in ('CHARACTERISTIC', 'AXIS_PTS', 'MEASUREMENT'):
            continue
        if name in src_names.get(typ, set()):
            continue
        owner = map_owner(owner_map, name) if owner_map else None
        if owner:
            if owner.lower() != model.lower():
                continue        # 归属明确且是别的模型: 绝不删
            candidates.append((b, 'MAP 定义方为本模型(%s), 新版无此对象' % owner))
            cand_keys.add((typ, name))
        else:
            if not cm_prefix:
                continue        # 无归属信息: 退回 CM 前缀判据
            m = _CM_REF_RE.search(b['text'])
            cm = m.group(1) if m else ''
            if not cm.startswith(cm_prefix):
                continue
            candidates.append((b, '引用本模型CM(%s), 新版无此对象' % cm))
            cand_keys.add((typ, name))
        m = _CM_REF_RE.search(b['text'])
        if m and '_CM_' in m.group(1):
            stale_families.add(m.group(1).split('_CM_')[0])

    # ---- 第二遍: GROUP 与 COMPU_METHOD ----
    # GROUP: longid 根是模型名, 或落在遗留对象的旧命名家族里. 后者是"模型内部子系统
    # 改过名"的场景 —— 老构建生成的组 (如 PTDISTR_PtTqEM) 名根既不是模型名也不属于
    # 其他在用模型, 但从"它引用的对象已被证明是遗留"可以确认它同属旧构建.
    for b in tgt_blocks:
        if b['type'] != 'GROUP':
            continue
        lid = b.get('longid', '') or ''
        root = lid.split('/')[0]
        if (lid == model or lid.startswith(model + '/') or b['name'] == model
                or root in stale_families or b['name'] in stale_families):
            candidates.append((b, 'GROUP 不再保留'))
            cand_keys.add(('GROUP', b['name']))

    # COMPU_METHOD: 前缀命中, 或仅被待删对象引用 (对象删完即成孤儿)
    cm_users = {}
    for b in tgt_blocks:
        if b['type'] in ('CHARACTERISTIC', 'AXIS_PTS', 'MEASUREMENT'):
            m = _CM_REF_RE.search(b['text'])
            if m:
                cm_users.setdefault(m.group(1), set()).add((b['type'], b['name']))
    for b in tgt_blocks:
        if b['type'] != 'COMPU_METHOD' or not b['name']:
            continue
        if b['name'] in src_names.get('COMPU_METHOD', set()):
            continue
        if cm_prefix and b['name'].startswith(cm_prefix):
            candidates.append((b, 'CM 前缀匹配, 新版无此转换方法'))
            cand_keys.add(('COMPU_METHOD', b['name']))
            continue
        users = cm_users.get(b['name'], set())
        if users and all(k in cand_keys for k in users):
            candidates.append((b, '仅被待删对象引用, 随对象一并清理'))
            cand_keys.add(('COMPU_METHOD', b['name']))

    full = ''.join(lines)
    line_starts = [0]
    idx = full.find('\n')
    while idx >= 0:
        line_starts.append(idx + 1)
        idx = full.find('\n', idx + 1)
    cand_ranges = sorted((b['start'], b['end']) for b, _ in candidates)
    # 同类型待删块互为引用候选区 (如 GROUP 之间 SUB_GROUP 互相引用,
    # 属整组待删集合, 不应互相阻止删除; 变量名不会被同名块引用, 不受影响)
    cand_ranges_by_type = {}
    for b, _ in candidates:
        cand_ranges_by_type.setdefault(b['type'], []).append((b['start'], b['end']))
    for k in cand_ranges_by_type:
        cand_ranges_by_type[k].sort()

    # 模型自身的 FUNCTION 块 (新版源文件同名 FUNCTION, 或名称以模型前缀开头).
    # 其内部的引用属于本模型自己的功能分组, 不阻止删除, 删除后同步清理引用行.
    src_func_names = src_names.get('FUNCTION', set())
    model_funcs = [b for b in tgt_blocks
                   if b['type'] == 'FUNCTION'
                   and (b['name'] in src_func_names
                        or b['name'] == model
                        or b['name'].startswith(model + '_'))]
    model_func_ranges = sorted((b['start'], b['end']) for b in model_funcs)
    # GROUP 名常与模型 FUNCTION 同名, 全部 FUNCTION 块内的同名出现均不计为引用
    all_func_ranges = sorted((b['start'], b['end']) for b in tgt_blocks if b['type'] == 'FUNCTION')

    def in_ranges(line_no, ranges):
        """已按起始行排序的区间列表, 二分判断行号是否落在任一区间内"""
        i = bisect.bisect_right(ranges, (line_no, 1 << 30)) - 1
        return i >= 0 and ranges[i][1] >= line_no

    def outside_refs(name, is_group=False):
        cnt = 0
        excl = all_func_ranges if is_group else model_func_ranges
        same_type_cand = cand_ranges_by_type.get('GROUP' if is_group else '', [])
        for m in re.finditer(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])',
                             full):
            line_no = bisect.bisect_right(line_starts, m.start()) - 1
            if line_no >= len(lines):
                continue
            if in_ranges(line_no, cand_ranges):
                continue
            if same_type_cand and in_ranges(line_no, same_type_cand):
                continue
            if in_ranges(line_no, excl):
                continue
            if is_group:
                # GROUP 名的真实引用只出现在其他 GROUP 的 SUB_GROUP 列表;
                # 自身名称定义行和带引号的 longid 路径串均不算引用
                if 'Name' in lines[line_no] and '*/' in lines[line_no]:
                    continue
                line_s, line_e = line_starts[line_no], line_starts[line_no + 1]
                for q in re.finditer(r'"[^"]*"', full[line_s:line_e]):
                    if q.start() + line_s <= m.start() < q.end() + line_s:
                        break
                else:
                    cnt += 1
                continue
            cnt += 1
        return cnt

    to_delete, kept = [], []
    for b, why in candidates:
        refs = outside_refs(b['name'], is_group=(b['type'] == 'GROUP'))
        if refs > 0:
            kept.append((b, why, refs))
        else:
            to_delete.append((b, why))

    to_delete.sort(key=lambda x: x[0]['start'])
    skip = set()
    for b, why in to_delete:
        for i in range(b['start'], b['end'] + 1):
            skip.add(i)
        nxt = b['end'] + 1
        if nxt < len(lines) and lines[nxt].strip() == '':
            skip.add(nxt)

    # 清理模型自身 FUNCTION 块中对已删对象的引用行, 避免残留悬空引用.
    # 引用行只可能出现在子节区 (DEF/REF/IN/OUT_MEASUREMENT 等),
    # 块头部的名称/长标识行不处理, 防止与已删 GROUP 同名时误删名称行
    deleted_names = {b['name'] for b, _ in to_delete}
    for s, e in model_func_ranges:
        first_sub = None
        for i in range(s + 1, min(e + 1, len(lines))):
            if '/begin ' in lines[i]:
                first_sub = i
                break
        if first_sub is None:
            continue
        for i in range(first_sub, min(e + 1, len(lines))):
            if lines[i].strip() in deleted_names:
                skip.add(i)

    # 清理其他块对已删组的引用: 组名会出现在 GROUP 的 SUB_GROUP 列表和
    # FUNCTION 的 SUB_FUNCTION 列表里. 不清理会在产物里留下悬空组名
    # (实测: PTDISTR_PtTqEM / PTDISTR_TqSpltStgy 删掉后仍被 SUB_FUNCTION 引用).
    deleted_groups = {b['name'] for b, _ in to_delete if b['type'] == 'GROUP'}
    if deleted_groups:
        in_sub = False
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith('/begin') and ('SUB_GROUP' in s or 'SUB_FUNCTION' in s):
                in_sub = True
                continue
            if s.startswith('/end') and ('SUB_GROUP' in s or 'SUB_FUNCTION' in s):
                in_sub = False
                continue
            if in_sub and i not in skip and s in deleted_groups:
                skip.add(i)

    out = [l for i, l in enumerate(lines) if i not in skip]

    # 清理内容已清空的旧版 "merged from model A2L" 标记区段 (含前后空行)
    cleaned = []
    i = 0
    while i < len(out):
        if 'BEGIN: merged from model A2L' in out[i]:
            j = i + 1
            while j < len(out) and 'END: merged from model A2L' not in out[j]:
                if out[j].strip():
                    break
                j += 1
            if j < len(out) and 'END: merged from model A2L' in out[j]:
                if i > 0 and out[i - 1].strip() == '':
                    cleaned.pop()
                i = j + 1
                if i < len(out) and out[i].strip() == '':
                    i += 1
                continue
        cleaned.append(out[i])
        i += 1
    return cleaned, {'deleted': to_delete, 'kept_warn': kept}


def _rebuild_model_function(lines, src_blocks, log):
    """同步完成后, 按目标中模型的最终对象集合重建其自身 FUNCTION 块.
    适用于源模型 A2L 不含 FUNCTION 块的情况 (FUNCTION 由本工具箱合并功能生成).
    归属判定: 块内 Conversion Method 引用本模型 CM 前缀.
    返回 (新行列表, 统计dict)"""
    if any(b['type'] == 'FUNCTION' for b in src_blocks):
        return lines, {'skipped': '源含 FUNCTION, 已在合并阶段同步'}

    model = None
    for b in src_blocks:
        if b['type'] == 'COMPU_METHOD' and '_CM_' in b['name']:
            model = b['name'].split('_CM_')[0]
            break
    if not model:
        return lines, {'skipped': '无法确定模型前缀'}
    cm_prefix = model + '_CM_'

    blocks, module_end = _parse_blocks(lines, need_text=True)
    blocks = [b for b in blocks if b.get('name')]

    # 模型最终对象集合 (按 CM 引用归属)
    members = {'CHARACTERISTIC': [], 'AXIS_PTS': [], 'MEASUREMENT': []}
    for b in blocks:
        typ = b['type']
        if typ == 'AXIS_PCAL':
            typ = 'AXIS_PTS'
        if typ not in members:
            continue
        m = _CM_REF_RE.search(b['text'])
        if m and m.group(1).startswith(cm_prefix):
            members[typ].append(b['name'])

    # 排序: 源文件出现顺序优先, 其余保持目标顺序 (稳定排序)
    pos = {}
    i = 0
    for b in src_blocks:
        t2 = 'AXIS_PTS' if b['type'] == 'AXIS_PCAL' else b['type']
        if t2 in members:
            pos[(t2, b['name'])] = i
            i += 1
    for typ in members:
        members[typ].sort(key=lambda n: pos.get((typ, n), 1 << 30))

    # 生成 FUNCTION 文本 (与合并功能的输出格式一致)
    nl = '\r\n' if any(l.endswith('\r\n') for l in lines[:100]) else '\n'
    out_lines = []
    out_lines.append('    /begin FUNCTION\n')
    out_lines.append('      %s\n' % model)
    out_lines.append('      ""\n\n')
    for sec, typ in (('DEF_CHARACTERISTIC', 'CHARACTERISTIC'),
                     ('REF_CHARACTERISTIC', 'AXIS_PTS'),
                     ('IN_MEASUREMENT', 'MEASUREMENT')):
        out_lines.append('      /begin %s\n' % sec)
        for n in members[typ]:
            out_lines.append('        %s\n' % n)
        out_lines.append('      /end %s\n\n' % sec)
    out_lines.append('      /begin OUT_MEASUREMENT\n')
    out_lines.append('      /end OUT_MEASUREMENT\n\n')
    out_lines.append('    /end FUNCTION\n')
    new_text = ''.join(out_lines).replace('\r\n', '\n').replace('\n', nl)

    # 定位模型自身 FUNCTION 块 (名称 == 模型名, 其次前缀匹配)
    func_blk = None
    for b in blocks:
        if b['type'] == 'FUNCTION' and b['name'] == model:
            func_blk = b
            break
    if func_blk is None:
        for b in blocks:
            if b['type'] == 'FUNCTION' and b['name'].startswith(model + '_'):
                func_blk = b
                break

    counts = {'DEF_CHARACTERISTIC': len(members['CHARACTERISTIC']),
              'REF_CHARACTERISTIC': len(members['AXIS_PTS']),
              'IN_MEASUREMENT': len(members['MEASUREMENT'])}

    if func_blk is not None:
        if _norm_for_compare(func_blk['text']) == _norm_for_compare(new_text):
            log('  FUNCTION 重建: %s 内容无变化, 保持' % func_blk['name'])
            return lines, {'name': func_blk['name'], 'changed': False, 'counts': counts}
        out = lines[:func_blk['start']] + new_text.splitlines(True) + lines[func_blk['end'] + 1:]
        log('  FUNCTION 重建: %s (DEF %d / REF %d / IN %d)' %
            (func_blk['name'], counts['DEF_CHARACTERISTIC'],
             counts['REF_CHARACTERISTIC'], counts['IN_MEASUREMENT']))
        return out, {'name': func_blk['name'], 'changed': True, 'counts': counts}

    # 目标没有该模型的 FUNCTION -> 插入 /end MODULE 之前
    if module_end is None:
        return lines, {'skipped': '未找到 /end MODULE, 无法新增 FUNCTION'}
    insert = new_text.splitlines(True)
    out = lines[:module_end] + [nl] + insert + [nl] + lines[module_end:]
    log('  FUNCTION 新增: %s (DEF %d / REF %d / IN %d)' %
        (model, counts['DEF_CHARACTERISTIC'],
         counts['REF_CHARACTERISTIC'], counts['IN_MEASUREMENT']))
    return out, {'name': model, 'changed': True, 'added': True, 'counts': counts}


# ==================== 主入口函数 ====================

def sync_model_a2l(src_path, tgt_path, out_path, purge=True, backup=True, log=None,
                   owner_map=None):
    """将新版模型 A2L 的对象同步进整车 A2L (保留已有 ECU 地址).
    purge=True 时删除旧版模型中已不存在的对象.
    owner_map: MAP 的 {符号: 定义模块}; 给了就按"定义方"裁决 ——
    本文件只是引用方(定义方是别的模型)且目标已有该对象时, 不覆盖目标, 避免用引用方的
    宽限值改掉定义方的真实限值.
    返回统计 dict"""
    t0 = time.time()
    log = log or (lambda m: None)

    log('[1/5] 解析新版模型 A2L ...')
    src_lines = _read_lines(src_path)
    src_blocks, _ = _parse_blocks(src_lines, need_text=True)
    src_blocks = [b for b in src_blocks if b.get('name')]
    # 源块里的生成器残留标注一律剥除, 避免同步时灌进整车 A2L (目标侧已有内容不动)
    for b in src_blocks:
        b['text'] = strip_addr_annotation(b['text'])
    log('  源块数: %d' % len(src_blocks))
    if not src_blocks:
        raise ValueError('源文件中未解析到任何对象块')

    log('[2/5] 解析目标 A2L ...')
    tgt_lines = _read_lines(tgt_path)
    tgt_blocks, module_end = _parse_blocks(tgt_lines, need_text=True)
    tgt_blocks = [b for b in tgt_blocks if b.get('name')]
    log('  目标顶层块数: %d' % len(tgt_blocks))
    if module_end is None:
        raise ValueError('目标文件中未找到 /end MODULE')

    if backup:
        bak = out_path + '.bak'
        shutil.copy2(tgt_path, bak)
        log('  已备份目标文件 -> %s' % bak)

    # 归属裁决: 本文件声明但不归它定义的对象, 不得覆盖目标里定义方的那一份
    head_model = _source_model_name(src_lines, src_path)
    model = head_model or Path(src_path).stem
    foreign = []
    skip_keys = set()
    if owner_map:
        foreign = _foreign_ref_keys(src_blocks, tgt_blocks, owner_map, model)
        skip_keys = {(t, n) for t, n, _ in foreign}
        log('  归属判定: 本模型 %s | 由别的模型定义且目标已存在的对象 %d 个, 将跳过覆盖'
            % (model, len(skip_keys)))

    log('[3/5] 合并 (更新/保留地址/新增) ...')
    out_lines, mstats = _merge_blocks(src_blocks, tgt_lines, tgt_blocks, module_end,
                                      skip_ref=skip_keys)
    cnt_r = Counter(tb['type'] for tb, _, _ in mstats['replacements'])
    cnt_a = Counter(sb['type'] for sb, _ in mstats['additions'])
    log('  替换/更新: %d 个 %s' % (len(mstats['replacements']), dict(cnt_r)))
    log('  新增: %d 个 %s' % (len(mstats['additions']), dict(cnt_a)))
    if mstats['skipped_ref']:
        log('  按定义方跳过 (本文件仅为引用方): %d 个 %s'
            % (len(mstats['skipped_ref']),
               dict(Counter(t for t, _ in mstats['skipped_ref']))))
        for t, n, own in foreign[:10]:
            log('    KEEP [%s] %s : 定义方 %s' % (t, n, own))
    if mstats['additions']:
        if mstats['insert_at'] != module_end:
            log('  新增块已原位插入模型区域之后 (第 %d 行)' % (mstats['insert_at'] + 1))
        else:
            log('  目标中无该模型已有对象, 新增块插入 /end MODULE 之前')
    for typ, name, why in mstats['kept_same']:
        log('  [保持] %s %s: %s' % (typ, name, why))

    pstats = {'deleted': [], 'kept_warn': []}
    if purge:
        log('[4/5] 清理旧版模型中已不存在的对象 ...')
        out_lines, pstats = _purge_blocks(out_lines, src_blocks, model=head_model,
                                          owner_map=owner_map)
        if pstats.get('note'):
            log('  ' + pstats['note'])
        log('  删除: %d 个' % len(pstats['deleted']))
        for b, why in pstats['deleted']:
            log('    DELETE [%s] %s : %s' % (b['type'], b['name'], why))
        for b, why, refs in pstats['kept_warn']:
            log('    [警告] [%s] %s 块外仍有 %d 处引用, 未删除' % (b['type'], b['name'], refs))
    else:
        log('[4/5] 清理已禁用, 跳过')

    log('[5/5] 重建模型 FUNCTION 块 ...')
    out_lines, fstats = _rebuild_model_function(out_lines, src_blocks, log)
    if fstats.get('skipped'):
        log('  跳过: %s' % fstats['skipped'])

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', errors='surrogateescape', newline='') as f:
        f.writelines(out_lines)

    log('输出: %s (共 %d 行, 耗时 %.1fs)' % (out_path, len(out_lines), time.time() - t0))

    return {
        'src_total': len(src_blocks),
        'replaced': len(mstats['replacements']),
        'replaced_by_type': dict(cnt_r),
        'added': len(mstats['additions']),
        'added_by_type': dict(cnt_a),
        'skipped_ref': len(mstats['skipped_ref']),
        'skipped_ref_names': ['[%s] %s : 定义方 %s' % (t, n, own) for t, n, own in foreign],
        'added_names': ['[%s] %s' % (sb['type'], sb['name']) for sb, _ in mstats['additions']],
        'kept_same': mstats['kept_same'],
        'deleted': len(pstats['deleted']),
        'deleted_names': ['[%s] %s' % (b['type'], b['name']) for b, _ in pstats['deleted']],
        'kept_warn': pstats['kept_warn'],
        'function': fstats,
        'no_addr_names': ['[%s] %s' % (sb['type'], sb['name']) for sb, _ in mstats['additions']
                          if sb['type'] in ('CHARACTERISTIC', 'AXIS_PTS', 'MEASUREMENT')],
    }


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 4:
        print("用法: python sync_engine.py <src_a2l> <tgt_a2l> <out_a2l> [purge] [backup]")
        sys.exit(1)
    
    src_path, tgt_path, out_path = sys.argv[1:4]
    purge = sys.argv[4].lower() in ('true', '1', 'yes') if len(sys.argv) > 4 else True
    backup = sys.argv[5].lower() in ('true', '1', 'yes') if len(sys.argv) > 5 else True
    
    try:
        stats = sync_model_a2l(src_path, tgt_path, out_path, purge=purge, backup=backup, log=print)
        print(f"\n同步完成:")
        print(f"  源对象数: {stats['src_total']}")
        print(f"  替换/更新: {stats['replaced']}")
        print(f"  新增: {stats['added']}")
        print(f"  删除: {stats['deleted']}")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)