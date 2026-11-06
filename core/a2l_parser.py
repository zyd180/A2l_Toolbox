#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A2L 文件解析模块 - 提取变量、块、内容"""

import re
from collections import OrderedDict
from pathlib import Path

from .map_parser import parse_map_ownership, map_owner
from .sync_engine import _read_lines_lf, strip_addr_annotation


def extract_a2l_variables(a2l_path):
    """提取 A2L 中的变量 (变量名 + 地址 + 块范围)"""
    lines = _read_lines_lf(a2l_path)
    
    variables = []
    current_var = None
    block_depth = 0
    
    name_pattern = re.compile(r'/\*\s*Name\s*\*/\s+([A-Za-z_]\w*)')
    addr_comment_pattern = re.compile(r'@ECU_Address@([A-Za-z_]\w*)@')
    ecu_addr_pattern = re.compile(r'ECU_ADDRESS\s+0[xX]([0-9A-Fa-f]+)')
    addr_only_pattern = re.compile(r'/\*\s*ECU\s+Address\s*\*/\s*0[xX]([0-9A-Fa-f]+)')
    begin_pattern = re.compile(r'/begin\s+(CHARACTERISTIC|MEASUREMENT|AXIS_PCAL|AXIS_PTS)', re.IGNORECASE)
    end_pattern = re.compile(r'/end\s+(CHARACTERISTIC|MEASUREMENT|AXIS_PCAL|AXIS_PTS)', re.IGNORECASE)
    
    for i, line in enumerate(lines):
        if not current_var:
            begin_match = begin_pattern.search(line)
            if begin_match:
                current_var = {
                    'name': None,
                    'name_line': None,
                    'addr_line': None,
                    'addr_value': None,
                    'varname_from_comment': None,
                    'begin_line': i + 1,
                    'end_line': None,
                    'block_type': begin_match.group(1)
                }
                block_depth = 1
                continue
        
        if current_var is None:
            continue
        
        block_depth += len(begin_pattern.findall(line))
        block_depth -= len(end_pattern.findall(line))
        
        if block_depth <= 0:
            current_var['end_line'] = i + 1
            if current_var['name'] and current_var['addr_line']:
                variables.append(current_var)
            current_var = None
            continue
        
        if current_var['name'] is None:
            name_match = name_pattern.search(line)
            if name_match:
                current_var['name'] = name_match.group(1)
                current_var['name_line'] = i + 1
        
        if current_var['addr_line'] is None:
            addr_match = ecu_addr_pattern.search(line)
            if not addr_match:
                addr_match = addr_only_pattern.search(line)
            if addr_match:
                addr_val = addr_match.group(1)
                comment_match = addr_comment_pattern.search(line)
                current_var['addr_line'] = i + 1
                current_var['addr_value'] = addr_val
                current_var['varname_from_comment'] = comment_match.group(1) if comment_match else None
    
    return variables, lines


def get_a2l_blocks(a2l_path):
    """从A2L文件中提取目标块 (RECORD_LAYOUT / CHARACTERISTIC / MEASUREMENT / AXIS_PTS / COMPU_METHOD)
    
    直接定位目标类型的 /begin ... /end 对，跳过 PROJECT/MODULE 等外层容器。
    返回每个块的: 名称, 类型, 完整行内容(从/begin到/end)
    """
    TARGET_TYPES = {'RECORD_LAYOUT', 'CHARACTERISTIC', 'MEASUREMENT', 'AXIS_PTS', 'AXIS_PCAL', 'COMPU_METHOD'}
    
    lines = _read_lines_lf(a2l_path)
    
    blocks = []
    # 匹配名称注释: /* Name */ 或 /* Name of CompuMethod */ 等变体
    name_pattern = re.compile(r'/\*\s*Name(?:\s+of\s+\w+)?\s*\*/\s+([A-Za-z_]\w*)')
    # /begin TYPE 同行直接跟名称 (ASAP2 标准写法, 如 "/begin RECORD_LAYOUT Scalar_UWORD")
    inline_name_pattern = re.compile(r'^\s*([A-Za-z_]\w*)\s*$')
    # 匹配所有 /begin TYPE
    begin_pattern = re.compile(r'/begin\s+(\w+)', re.IGNORECASE)
    # 匹配所有 /end TYPE
    end_pattern = re.compile(r'/end\s+(\w+)', re.IGNORECASE)
    
    current_block = None
    block_depth = 0
    
    for line in lines:
        # 如果不在块内，检测目标块开始
        if current_block is None:
            begin_match = begin_pattern.search(line)
            if begin_match:
                block_type = begin_match.group(1).upper()
                if block_type in TARGET_TYPES:
                    current_block = {
                        'type': begin_match.group(1),
                        'name': None,
                        'lines': [line]
                    }
                    # 名称两种写法都要认: 同行 /begin TYPE NAME (标准 A2L, 如 RECORD_LAYOUT),
                    # 或下一行的 /* Name */ NAME 注释 (Simulink 生成风格)。
                    # 只认后者会让 RECORD_LAYOUT 全部无名, 合并时被整批丢弃。
                    m_inline = inline_name_pattern.match(
                        line[begin_match.end():])
                    if m_inline:
                        current_block['name'] = m_inline.group(1)
                    block_depth = 1
                    continue
            continue
        
        # 在块内，追加行
        current_block['lines'].append(line)
        
        # 匹配名称
        if current_block['name'] is None:
            name_match = name_pattern.search(line)
            if name_match:
                current_block['name'] = name_match.group(1)
        
        # 跟踪嵌套深度
        begins = begin_pattern.findall(line)
        ends = end_pattern.findall(line)
        block_depth += len(begins) - len(ends)
        
        if block_depth <= 0:
            blocks.append(current_block)
            current_block = None
    
    return blocks


# 生成器残留的地址标注 /* @ECU_Address@Name@ */ 由 _indent_block 统一剥除
# (规则与说明集中在 sync_engine.strip_addr_annotation, 合并/同步共用一份实现)
def _indent_block(lines, base=4, strip_annotation=True):
    """把块文本重排为统一缩进: 块头 base 个空格, 内部保留相对层级.

    原实现是无条件给每行再加 4 空格, 而原始行本身已带缩进, 叠加后每个块头变成 8 空格,
    整个合并产物体积凭空多出约 1.8MB (58 万行 x 4 字节), 也难和别家工具的输出对齐。
    这里改为"按块首行缩进归零后平移", 既保留 AXIS_DESCR 等嵌套层级, 又不重复叠加;
    同时清掉空行的尾随空格, 并剥掉生成器的 @ECU_Address@ 残留标注。
    """
    if not lines:
        return ''
    head_indent = len(lines[0]) - len(lines[0].lstrip(' '))
    out = []
    for ln in lines:
        s = ln.rstrip('\r\n')
        if strip_annotation:
            s = strip_addr_annotation(s)
        s = s.rstrip()
        if not s:
            out.append('\n')
            continue
        lead = len(s) - len(s.lstrip(' '))
        rel = lead - head_indent
        if rel < 0:
            rel = 0
        out.append(' ' * (base + rel) + s.lstrip(' ') + '\n')
    return ''.join(out)


def extract_a2l_content(folder_path, recursive=True, map_path=None, log=None):
    """从文件夹下所有 A2L 文件提取合并所需的内容, 同名对象按"定义方"去重

    返回 (record_lines, variable_blocks, compu_lines, file_var_map, file_count, dedup):
        record_lines: RECORD_LAYOUT 块的去重合集 (带 4 空格缩进)
        variable_blocks: 变量定义块列表 (CHARACTERISTIC/MEASUREMENT/AXIS_PTS 等, 已去重)
        compu_lines: COMPU_METHOD 块的去重合集
        file_var_map: {file_stem: {'CHARACTERISTIC': [...], 'AXIS_PTS': [...], 'MEASUREMENT': [...]}}
        dedup: 去重统计与冲突清单

    关于去重: 同一个对象常被多个模型 A2L 声明 —— 定义它的那个 SWC 声明一次, 其余是引用方。
    A2L 本身没有 owner 字段 (MODULE 名在 Simulink 输出里是通用的 ModuleName), 因此按以下
    优先级裁决保留哪一份:
        1. MAP 的"定义模块(.o)" == 某声明文件的模型  -> 用那份      (权威)
        2. 变量名前缀 == 某声明文件的模型前缀(忽略大小写), 且唯一   -> 用那份
        3. 各副本结构指纹一致(仅长标识/CM名/地址不同)              -> 取文件名首个
        4. 结构确有差异(典型是限值) -> 取限值更紧的 (引用方常用 uint8 兜底 255,
           定义方是真实枚举范围, 取宽的那个会允许越界写入)          -> 并记入冲突清单
    """
    log = log or (lambda m: None)
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"无效的文件夹: {folder_path}")

    pattern = '**/*.a2l' if recursive else '*.a2l'
    a2l_files = sorted(list(folder.glob(pattern)))

    if not a2l_files:
        raise ValueError(f"在 {folder_path} 中未找到 A2L 文件")

    map_idx = parse_map_ownership(map_path) if map_path else {}
    if map_path:
        log('  符号归属索引: %d 个符号 (来自 %s)' % (len(map_idx), Path(map_path).name))
        if not map_idx:
            log('  [警告] 该 MAP 无 ".o" 列, 无法判定定义模块, 已降级为启发式')

    # 收集数据
    record_lines = []
    record_added = set()
    var_groups = OrderedDict()      # (type,name) -> [(file_key, model, block_text)]
    compu_lines = []
    compu_added = set()
    file_var_map = {}               # 按文件分组
    unnamed = 0

    for a2l_file in a2l_files:
        file_key = a2l_file.stem
        model = _model_name_of(a2l_file, file_key)
        file_var_map[file_key] = {'CHARACTERISTIC': [], 'AXIS_PTS': [], 'AXIS_PCAL': [], 'MEASUREMENT': []}

        blocks = get_a2l_blocks(str(a2l_file))

        for block in blocks:
            block_type = block.get('type', '').upper()
            block_name = block.get('name', '')

            # 统一缩进 (块头 4 空格, 内部保留相对层级; 不叠加原缩进)
            block_text = _indent_block(block['lines'])

            if block_type == 'RECORD_LAYOUT':
                # 按名称去重
                if block_name and block_name not in record_added:
                    record_added.add(block_name)
                    record_lines.append(block_text)
            elif block_type == 'COMPU_METHOD':
                # 按名称去重
                if block_name and block_name not in compu_added:
                    compu_added.add(block_name)
                    compu_lines.append(block_text)
            elif block_type in ('CHARACTERISTIC', 'MEASUREMENT', 'AXIS_PTS', 'AXIS_PCAL'):
                key = (block_type, block_name) if block_name else ('', '__noname_%d' % unnamed)
                if not block_name:
                    unnamed += 1
                var_groups.setdefault(key, []).append((file_key, model, block_text))
                if block_name and block_type in file_var_map[file_key]:
                    file_var_map[file_key][block_type].append(block_name)

    variable_blocks = []
    dedup = {'groups': len(var_groups), 'duplicated': 0, 'by_map': 0, 'by_prefix': 0,
             'by_equal': 0, 'by_limit': 0, 'by_struct': 0, 'conflicts': [],
             'map_symbol_hits': 0}
    for (block_type, block_name), cands in var_groups.items():
        chosen, reason = _pick_owner(block_name, cands, map_idx)
        variable_blocks.append(chosen[2])
        if len(cands) < 2:
            continue
        dedup['duplicated'] += 1
        if map_idx and map_owner(map_idx, block_name):
            dedup['map_symbol_hits'] += 1
        bucket = {'MAP定义模块': 'by_map', '名称前缀': 'by_prefix',
                  '内容等价': 'by_equal', '限值更紧': 'by_limit',
                  '结构差异': 'by_struct'}.get(reason)
        if bucket:
            dedup[bucket] += 1
        fps = {_struct_fingerprint(c[2]) for c in cands}
        if len(fps) > 1:
            chosen_fp = _struct_fingerprint(chosen[2])
            dedup['conflicts'].append({
                'name': block_name, 'type': block_type, 'chosen': chosen[0],
                'reason': reason,
                # (文件, 模型, 下限, 上限, 是否与保留项等价)
                'candidates': [(c[0], c[1]) + _limits(c[2])
                               + (_struct_fingerprint(c[2]) == chosen_fp,)
                               for c in cands]})

    if dedup['duplicated']:
        log('  同名对象去重: %d 组 -> %d 组' % (dedup['duplicated'],
                                              dedup['groups'] - dedup['duplicated']))
        log('    按 MAP 定义模块: %d | 名称前缀: %d | 内容等价: %d | 限值更紧: %d | 结构差异取首个: %d'
            % (dedup['by_map'], dedup['by_prefix'], dedup['by_equal'],
               dedup['by_limit'], dedup['by_struct']))
        if map_idx:
            # MAP 里查得到符号 != 能定位到声明该对象的文件; 命中率过低通常意味着
            # MAP 与这批 A2L 不是同一次构建, 此时实际上退化为启发式, 必须提示
            rate = 100.0 * dedup['by_map'] / dedup['duplicated']
            log('    MAP 覆盖: 符号命中 %d/%d 组, 可定位到声明文件 %d 组 (%.1f%%)'
                % (dedup['map_symbol_hits'], dedup['duplicated'],
                   dedup['by_map'], rate))
            if dedup['map_symbol_hits'] and rate < 50.0:
                log('    [警告] MAP 命中率过低, 该 MAP 很可能与这批 A2L 不是同一次构建,'
                    ' 已大量退化为启发式裁决')
        if dedup['conflicts']:
            log('    结构差异(需复核): %d 项' % len(dedup['conflicts']))
            for c in dedup['conflicts'][:10]:
                log('      %s [%s] 保留 %s (%s), 候选 %d 份'
                    % (c['name'], c['type'], c['chosen'], c['reason'], len(c['candidates'])))
            if len(dedup['conflicts']) > 10:
                log('      ... 其余 %d 项见去重报告' % (len(dedup['conflicts']) - 10))

    return (record_lines, variable_blocks, compu_lines, file_var_map,
            len(a2l_files), dedup)


# ==================== 同名对象归属判定 ====================

_MODEL_RE = re.compile(r'Code generation for model\s+"([^"]+)"')
_UP_LIMIT_RE = re.compile(r'Upper [Ll]imit\s*\*/\s*([-+]?[\d.]+(?:[eE][+-]?\d+)?)')
_LO_LIMIT_RE = re.compile(r'Lower [Ll]imit\s*\*/\s*([-+]?[\d.]+(?:[eE][+-]?\d+)?)')
def _model_name_of(path, stem):
    """文件所属模型名: 优先 Simulink 头部注释, 否则用文件名"""
    try:
        with open(path, 'r', encoding='utf-8', errors='surrogateescape') as f:
            head = f.read(4096)
    except OSError:
        return stem
    m = _MODEL_RE.search(head)
    return m.group(1) if m else stem


_NUM_TOKEN_RE = re.compile(r'(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.])')


def _canon_num(m):
    try:
        return '%.12g' % float(m.group(0))
    except ValueError:
        return m.group(0)


def _struct_fingerprint(text):
    """结构指纹: 去掉长标识/地址/CM名/空白与 begin-end 记号, 数字归一化后只留形状与限值

    数字必须归一化: 同一个限值在不同生成器里可能是 `4294967295` / `4.294967295E+9`,
    `0` / `0.0`, 不归一化会把纯格式差异误判成结构冲突。
    """
    t = re.sub(r'\s+', ' ', text)
    t = re.sub(r'"[^"]*"', ' ', t)
    # 地址标注注释 /* @ECU_Address@Name@ */ 只是标记, 有它没它不算结构差异
    t = re.sub(r'@ECU_Address@[^@]*@', ' ', t)
    t = re.sub(r'/\*\s*\*/', ' ', t)      # 剥掉标注后残留的空注释
    t = re.sub(r'0[xX][0-9A-Fa-f]+', ' ', t)
    t = re.sub(r'Conversion [Mm]ethod\s*\*/\s*\w+', 'CM', t)
    t = re.sub(r'/\s*(begin|end)\s+\w+', ' ', t)
    t = _NUM_TOKEN_RE.sub(_canon_num, t)
    # 去掉地址/标注后会留下连续空白, 必须再收敛一次, 否则纯空格差异会被当成结构冲突
    return re.sub(r'\s+', ' ', t).strip()


def _limits(text):
    """(下限, 上限); 缺任一端返回 (None, None)"""
    mu, ml = _UP_LIMIT_RE.search(text), _LO_LIMIT_RE.search(text)
    if not mu or not ml:
        return None, None
    try:
        return float(ml.group(1)), float(mu.group(1))
    except ValueError:
        return None, None


def _limit_span(text):
    """上下限跨度; 缺任一端返回 None"""
    lo, hi = _limits(text)
    return None if lo is None else hi - lo


def _pick_owner(name, cands, map_idx):
    """在多个候选块中选"定义方"那一份. 返回 (候选, 理由)"""
    cands = sorted(cands, key=lambda c: c[0].lower())
    if len(cands) == 1:
        return cands[0], '唯一'

    owner = map_owner(map_idx, name)
    if owner:
        hit = [c for c in cands if c[1].lower() == owner.lower()]
        if hit:
            return hit[0], 'MAP定义模块'

    pref = name.split('_')[0].lower() if name else ''
    if pref:
        hit = [c for c in cands if c[1].lower().split('_')[0] == pref]
        if len(hit) == 1:
            return hit[0], '名称前缀'

    if len({_struct_fingerprint(c[2]) for c in cands}) == 1:
        return cands[0], '内容等价'

    spans = {_limit_span(c[2]) for c in cands}
    if len(spans) == 1:
        # 限值一致但仍有其它结构差异 (类型/布局/采样等): 无法用限值裁决, 取首个
        return cands[0], '结构差异'

    def key(c):
        span = _limit_span(c[2])
        return (span if span is not None else float('inf'), c[0].lower())

    return min(cands, key=key), '限值更紧'


def build_function_blocks(file_var_map):
    """根据 file_var_map 生成 FUNCTION 块文本"""
    output_lines = []
    function_names = []
    
    for file_key, var_dict in file_var_map.items():
        CHARACTERISTIC_list = var_dict.get('CHARACTERISTIC', [])
        AXIS_PTS_list = var_dict.get('AXIS_PTS', []) + var_dict.get('AXIS_PCAL', [])
        MEASUREMENT_list = var_dict.get('MEASUREMENT', [])
        
        # 跳过空文件
        if not CHARACTERISTIC_list and not AXIS_PTS_list and not MEASUREMENT_list:
            continue
        
        function_names.append(file_key)
        
        output_lines.append("    /begin FUNCTION\n")
        output_lines.append(f"      {file_key}\n")
        output_lines.append('      ""\n\n')
        
        # DEF_CHARACTERISTIC
        if CHARACTERISTIC_list:
            output_lines.append("      /begin DEF_CHARACTERISTIC\n")
            for name in CHARACTERISTIC_list:
                output_lines.append(f"        {name}\n")
            output_lines.append("      /end DEF_CHARACTERISTIC\n\n")
        
        # REF_CHARACTERISTIC (AXIS 引用)
        if AXIS_PTS_list:
            output_lines.append("      /begin REF_CHARACTERISTIC\n")
            for name in AXIS_PTS_list:
                output_lines.append(f"        {name}\n")
            output_lines.append("      /end REF_CHARACTERISTIC\n\n")
        else:
            output_lines.append("      /begin REF_CHARACTERISTIC\n")
            output_lines.append("      /end REF_CHARACTERISTIC\n\n")
        
        # IN_MEASUREMENT
        if MEASUREMENT_list:
            output_lines.append("      /begin IN_MEASUREMENT\n")
            for name in MEASUREMENT_list:
                output_lines.append(f"        {name}\n")
            output_lines.append("      /end IN_MEASUREMENT\n\n")
        else:
            output_lines.append("      /begin IN_MEASUREMENT\n")
            output_lines.append("      /end IN_MEASUREMENT\n\n")
        
        # OUT_MEASUREMENT
        output_lines.append("      /begin OUT_MEASUREMENT\n")
        output_lines.append("      /end OUT_MEASUREMENT\n\n")
        
        output_lines.append("    /end FUNCTION\n\n")
    
    # VCU_MODULE 顶层 FUNCTION
    if function_names:
        output_lines.append("    /begin FUNCTION VCU_MODULE\n")
        output_lines.append('      ""\n\n')
        output_lines.append("      /begin SUB_FUNCTION\n")
        for fname in function_names:
            output_lines.append(f"        {fname}\n")
        output_lines.append("      /end SUB_FUNCTION\n\n")
        output_lines.append("    /end FUNCTION\n\n")
    
    return ''.join(output_lines)


def write_content_only(record_lines, variable_blocks, compu_lines, file_var_map, output_path):
    """输出去壳的独立A2L内容 (RECORD_LAYOUT + 变量 + COMPU_METHOD + FUNCTION)"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        # RECORD_LAYOUT
        for line in record_lines:
            f.write(line)
        if record_lines:
            f.write("\n")
        
        # 变量定义
        for block_text in variable_blocks:
            f.write(block_text)
            f.write("\n")
        
        # COMPU_METHOD
        if compu_lines:
            for line in compu_lines:
                f.write(line)
            f.write("\n")
        
        # FUNCTION 块
        func_text = build_function_blocks(file_var_map)
        f.write(func_text)


# 地址行替换模式: 与 extract_a2l_variables 中的两种地址格式对应
_ADDR_SUB_PATTERNS = (
    re.compile(r'(ECU_ADDRESS\s+)0[xX][0-9A-Fa-f]+'),
    re.compile(r'(/\*\s*ECU\s+Address\s*\*/\s*)0[xX][0-9A-Fa-f]+'),
)


def _replace_line_addr(line, addr):
    """把地址行中的 ECU 地址替换为新值 (保留前缀), 未匹配返回 None"""
    new = '0x%08X' % addr
    for pat in _ADDR_SUB_PATTERNS:
        out, n = pat.subn(lambda m: m.group(1) + new, line, count=1)
        if n:
            return out
    return None


def update_a2l_file(a2l_path, symbols, out_path, remove_unmatched=False,
                    only_missing=False):
    """根据符号表更新 A2L 中变量的 ECU 地址 (按变量名精确匹配).
    remove_unmatched=True 时删除符号表中没有的变量块.
    only_missing=True 时只填补 0x0000 占位, 已带真实地址的对象不改写
    (用于"往整车 A2L 追加新模型"场景: 避免用另一次构建的 MAP 把已有地址整体搬走).
    返回 (total, matched, updated, elf_only_vars, stats);
    stats: {'unchanged': 地址未变, 'unmatched': 未匹配数, 'removed_count': 已删除块数,
            'kept_existing': 因 only_missing 而保留原地址数}
    """
    variables, lines = extract_a2l_variables(a2l_path)
    total = len(variables)

    matched = updated = unchanged = removed = kept_existing = 0
    unmatched_vars = []
    used_names = set()

    for var in variables:
        name = var['name']
        used_names.add(name)
        sym_addr = symbols.get(name)
        if sym_addr is None and var.get('varname_from_comment'):
            # 地址注释中的变量名作为兜底 (/* @ECU_Address@Name@ */)
            sym_addr = symbols.get(var['varname_from_comment'])
        if sym_addr is None:
            unmatched_vars.append(var)
            continue
        matched += 1
        old_addr = int(var['addr_value'], 16) if var['addr_value'] else None
        if old_addr == sym_addr:
            unchanged += 1
            continue
        if only_missing and old_addr:
            # 已有真实地址, 不覆盖
            kept_existing += 1
            continue
        new_line = _replace_line_addr(lines[var['addr_line'] - 1], sym_addr)
        if new_line is not None:
            lines[var['addr_line'] - 1] = new_line
            updated += 1
        else:
            unchanged += 1

    if remove_unmatched and unmatched_vars:
        skip = set()
        for var in unmatched_vars:
            for i in range(var['begin_line'] - 1, var['end_line']):
                skip.add(i)
            nxt = var['end_line']
            if nxt < len(lines) and lines[nxt].strip() == '':
                skip.add(nxt)
        lines = [l for i, l in enumerate(lines) if i not in skip]
        removed = len(unmatched_vars)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    elf_only = sorted(n for n in symbols if n not in used_names)
    stats = {'unchanged': unchanged, 'unmatched': total - matched,
             'removed_count': removed, 'kept_existing': kept_existing}
    return total, matched, updated, elf_only, stats


def _block_name_of(block_text):
    """从块文本取名称: 同行 /begin TYPE NAME 优先, 其次 /* Name */ 注释 (与 get_a2l_blocks 一致)"""
    head = block_text.lstrip()
    m = re.match(r'/begin\s+\w+\s*', head, re.IGNORECASE)
    if m:
        same_line = head[m.end():].split('\n', 1)[0].strip()
        mm = re.match(r'([A-Za-z_]\w*)$', same_line)
        if mm:
            return mm.group(1)
    nm = re.search(r'/\*\s*Name(?:\s+of\s+\w+)?\s*\*/\s+([A-Za-z_]\w*)', block_text)
    return nm.group(1) if nm else None


def insert_into_header(header_path, record_lines, variable_blocks, compu_lines, file_var_map, output_path, log=None):
    """将提取的内容插入头文件的 Data 标记处

    头文件自带的 RECORD_LAYOUT / COMPU_METHOD 不再重复写入: 项目实际使用的头文件模板
    已包含全套标准布局 (Scalar_*/Lookup1D_*/Lookup2D_*), 若照抄一遍会造成每个结构名
    定义两次 (实测 45 -> 90), 严格解析器会视为重复定义。
    """
    log = log or (lambda m: None)
    header_lines = _read_lines_lf(header_path)

    # 头文件已有的结构/转换方法名, 合并时跳过
    existing = set()
    for b in get_a2l_blocks(header_path):
        typ = b['type'].upper()
        if typ in ('RECORD_LAYOUT', 'COMPU_METHOD') and b.get('name'):
            existing.add((typ, b['name']))
    if existing:
        before = (len(record_lines), len(compu_lines))
        record_lines = [t for t in record_lines
                        if ('RECORD_LAYOUT', _block_name_of(t)) not in existing]
        compu_lines = [t for t in compu_lines
                       if ('COMPU_METHOD', _block_name_of(t)) not in existing]
        skipped_rl = before[0] - len(record_lines)
        skipped_cm = before[1] - len(compu_lines)
        if skipped_rl or skipped_cm:
            log('  头文件已定义, 跳过重复: RECORD_LAYOUT %d, COMPU_METHOD %d'
                % (skipped_rl, skipped_cm))

    # 匹配 Data 标记 (宽松匹配 /* ... Data ... */)
    data_marker_pattern = re.compile(r'/\*.*?\*+\s*Data\s*\*+.*?\*/', re.IGNORECASE | re.DOTALL)
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        # 1. 写入 Data 标记之前的所有内容 (含 Data 标记行本身)
        marker_found = False
        for line in header_lines:
            if not marker_found and data_marker_pattern.search(line):
                marker_found = True
                f.write(line)  # 写入 Data 标记行本身
                break
            f.write(line)
        
        if not marker_found:
            raise ValueError(f"在头文件 {header_path} 中未找到 Data 注释标记")
        
        # 2. 写入 RECORD_LAYOUT
        for line in record_lines:
            f.write(line)
        if record_lines:
            f.write("\n")
        
        # 4. 写入变量定义
        for block_text in variable_blocks:
            f.write(block_text)
            f.write("\n")
        
        # 5. 写入 COMPU_METHOD
        if compu_lines:
            for line in compu_lines:
                f.write(line)
            f.write("\n")
        
        # 6. 写入 FUNCTION 块
        func_text = build_function_blocks(file_var_map)
        f.write(func_text)
        
        # 7. 写入尾部
        f.write("  /end MODULE\n\n")
        f.write("/end PROJECT\n")


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python a2l_parser.py <a2l_file_or_folder>")
        sys.exit(1)
    
    path = sys.argv[1]
    try:
        if Path(path).is_dir():
            record_lines, variable_blocks, compu_lines, file_var_map, file_count, dedup = \
                extract_a2l_content(path, log=print)
            print(f"文件数: {file_count}")
            print(f"变量块: {len(variable_blocks)}")
            print(f"RECORD_LAYOUT: {len(record_lines)}")
            print(f"COMPU_METHOD: {len(compu_lines)}")
            print(f"去重: {dedup['duplicated']} 组")
        else:
            variables, _ = extract_a2l_variables(path)
            print(f"变量数: {len(variables)}")
            for v in variables[:10]:
                print(f"  {v['name']:40s} 行{v['addr_line']}")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)