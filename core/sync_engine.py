#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模型版本同步模块 - 将新版模型 A2L 的对象同步进整车 A2L"""

import re
import bisect
import shutil
import time
from collections import Counter
from pathlib import Path


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
_CM_REF_RE = re.compile(r'Conversion [Mm]ethod\s*\*/\s*([A-Za-z_][A-Za-z0-9_]*)')


# ==================== 工具函数 ====================

def _read_lines(path):
    with open(path, 'r', encoding='utf-8', errors='surrogateescape', newline='') as f:
        return f.readlines()


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
    m = (_ADDR_MEAS_GET_RE.search(b['text']) if b['type'] == 'MEASUREMENT'
         else _ADDR_CHAR_GET_RE.search(b['text']))
    return m.group(1) if m else None


def _merge_addr(src_text, typ, tgt_addr):
    """把目标真实地址写回源块文本(源为 0x0000 占位符时)"""
    if not tgt_addr or tgt_addr == '0x0000':
        return src_text, False
    if typ == 'MEASUREMENT':
        new, n = _ADDR_MEAS_RE.subn(r'\g<1>' + tgt_addr, src_text, count=1)
    elif typ in ('CHARACTERISTIC', 'AXIS_PTS'):
        new, n = _ADDR_CHAR_RE.subn(r'\g<1>' + tgt_addr, src_text, count=1)
    else:
        return src_text, False
    return new, n > 0


def _norm_for_compare(text):
    """归一化后比较: 去掉 ECU 地址、长标识字符串、多余空白"""
    t = re.sub(r'0x[0-9A-Fa-f]+', ' ', text)
    t = re.sub(r'"[^"]*"', ' ', t)
    t = re.sub(r'[ \t\r\n]+', ' ', t)
    return t.strip()


# ==================== 核心同步逻辑 ====================

def _merge_blocks(src_blocks, tgt_lines, tgt_blocks, module_end):
    """将源块合并进目标: 同名块原位更新(保留地址), FUNCTION 同名整体更新,
    缺失的新增块直接插入目标中该模型原有区域之后 (GROUP 不同步不保留).
    返回 (新行列表, 统计dict)"""
    tgt_by_key = {}
    for b in tgt_blocks:
        tgt_by_key.setdefault((b['type'], b['name']), []).append(b)

    replacements = []
    additions = []
    kept_same = []

    for sb in src_blocks:
        typ, name = sb['type'], sb['name']
        if typ == 'GROUP':
            # GROUP 不再同步/保留, 直接跳过
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
             'kept_same': kept_same, 'insert_at': insert_at}
    return out, stats


def _purge_blocks(lines, src_blocks):
    """删除旧版模型中已不存在的对象.
    归属判定: CM 名称前缀 / 块内引用本模型 CM.
    本模型的 GROUP 块不再保留, 清理时全部删除.
    删除前检查对象名在待删块之外是否仍被引用, 有残留引用则保留;
    模型自身 FUNCTION 块内的引用不阻止删除 (GROUP 则排除全部 FUNCTION 块内的
    同名出现, 避免与 FUNCTION 重名误判), 并同步清理其引用行.
    返回 (新行列表, 统计dict)"""
    src_names = {}
    for b in src_blocks:
        if not b.get('name'):
            continue
        src_names.setdefault(b['type'], set()).add(b['name'])

    model = None
    for b in src_blocks:
        if b['type'] == 'COMPU_METHOD' and '_CM_' in b['name']:
            model = b['name'].split('_CM_')[0]
            break
    if not model:
        return lines, {'deleted': [], 'kept_warn': [],
                       'note': '源文件未找到模型前缀的 COMPU_METHOD, 跳过清理'}
    cm_prefix = model + '_CM_'

    tgt_blocks, _ = _parse_blocks(lines, need_text=True)
    tgt_blocks = [b for b in tgt_blocks if b.get('name')]

    candidates = []
    for b in tgt_blocks:
        typ, name = b['type'], b['name']
        if typ == 'COMPU_METHOD' and name.startswith(cm_prefix) \
                and name not in src_names.get('COMPU_METHOD', set()):
            candidates.append((b, 'CM 前缀匹配, 新版无此转换方法'))
        elif typ == 'GROUP':
            lid = b.get('longid', '')
            if lid == model or lid.startswith(model + '/'):
                candidates.append((b, 'GROUP 不再保留'))
        elif typ in ('CHARACTERISTIC', 'AXIS_PTS', 'MEASUREMENT'):
            m = _CM_REF_RE.search(b['text'])
            cm = m.group(1) if m else ''
            if cm.startswith(cm_prefix) and name not in src_names.get(typ, set()):
                candidates.append((b, '引用本模型CM(%s), 新版无此对象' % cm))

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

def sync_model_a2l(src_path, tgt_path, out_path, purge=True, backup=True, log=None):
    """将新版模型 A2L 的对象同步进整车 A2L (保留已有 ECU 地址).
    purge=True 时删除旧版模型中已不存在的对象.
    返回统计 dict"""
    t0 = time.time()
    log = log or (lambda m: None)

    log('[1/5] 解析新版模型 A2L ...')
    src_lines = _read_lines(src_path)
    src_blocks, _ = _parse_blocks(src_lines, need_text=True)
    src_blocks = [b for b in src_blocks if b.get('name')]
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

    log('[3/5] 合并 (更新/保留地址/新增) ...')
    out_lines, mstats = _merge_blocks(src_blocks, tgt_lines, tgt_blocks, module_end)
    cnt_r = Counter(tb['type'] for tb, _, _ in mstats['replacements'])
    cnt_a = Counter(sb['type'] for sb, _ in mstats['additions'])
    log('  替换/更新: %d 个 %s' % (len(mstats['replacements']), dict(cnt_r)))
    log('  新增: %d 个 %s' % (len(mstats['additions']), dict(cnt_a)))
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
        out_lines, pstats = _purge_blocks(out_lines, src_blocks)
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