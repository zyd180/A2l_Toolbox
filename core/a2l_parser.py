#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A2L 文件解析模块 - 提取变量、块、内容"""

import re
from pathlib import Path


def extract_a2l_variables(a2l_path):
    """提取 A2L 中的变量 (变量名 + 地址 + 块范围)"""
    with open(a2l_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
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
    
    with open(a2l_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    blocks = []
    # 匹配名称注释: /* Name */ 或 /* Name of CompuMethod */ 等变体
    name_pattern = re.compile(r'/\*\s*Name(?:\s+of\s+\w+)?\s*\*/\s+([A-Za-z_]\w*)')
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


def extract_a2l_content(folder_path, recursive=True):
    """从文件夹下所有A2L文件提取合并所需的内容
    
    返回:
        record_lines: RECORD_LAYOUT 块的去重合集 (带 4 空格缩进)
        variable_blocks: 变量定义块列表 (CHARACTERISTIC/MEASUREMENT/AXIS_PTS 等)
        compu_lines: COMPU_METHOD 块的去重合集
        file_var_map: {file_stem: {'CHARACTERISTIC': [...], 'AXIS_PTS': [...], 'MEASUREMENT': [...]}}
    """
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"无效的文件夹: {folder_path}")
    
    pattern = '**/*.a2l' if recursive else '*.a2l'
    a2l_files = sorted(list(folder.glob(pattern)))
    
    if not a2l_files:
        raise ValueError(f"在 {folder_path} 中未找到 A2L 文件")
    
    # 收集数据
    record_lines = []
    record_added = set()
    variable_blocks = []
    compu_lines = []
    compu_added = set()
    file_var_map = {}  # 按文件分组
    
    for a2l_file in a2l_files:
        file_key = a2l_file.stem
        file_var_map[file_key] = {'CHARACTERISTIC': [], 'AXIS_PTS': [], 'AXIS_PCAL': [], 'MEASUREMENT': []}
        
        blocks = get_a2l_blocks(str(a2l_file))
        
        for block in blocks:
            block_type = block.get('type', '').upper()
            block_name = block.get('name', '')
            
            # 给每行添加 4 空格缩进
            indented_lines = [f"    {line}" for line in block['lines']]
            block_text = ''.join(indented_lines)
            
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
                variable_blocks.append(block_text)
                if block_name and block_type in file_var_map[file_key]:
                    file_var_map[file_key][block_type].append(block_name)
    
    return record_lines, variable_blocks, compu_lines, file_var_map, len(a2l_files)


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


def get_calibration_objects(a2l_path):
    """获取所有标定量对象（含地址、数据类型、转换公式、所属FUNCTION）
    
    返回: {
        'objects': [{
            'name': '标定量名称',
            'addr': 0x12345678,
            'data_type': 'FLOAT32_IEEE',
            'cm': '转换方法名',
            'char_type': 'VALUE/CURVE/MAP/etc',
            'function': '所属FUNCTION名称',
            'longid': '长标识字符串',
            'axes': [{'type': 'COM_AXIS', 'cm': '...', 'ref': '...', 'n': 10}],
        }],
        'cms': {'cm_name': {'conv': 'RAT_FUNC', 'coeffs': (a,b,c,d,e,f), 'byte_order': '...'}},
        'functions': {'func_name': ['var1', 'var2', ...]}
    }
    """
    with open(a2l_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # 先解析FUNCTION块，建立变量名到FUNCTION的映射
    functions = {}
    func_pattern = re.compile(r'/begin\s+FUNCTION\s+(\w+)(.*?)/end\s+FUNCTION', re.DOTALL | re.IGNORECASE)
    def_char_pattern = re.compile(r'/begin\s+DEF_CHARACTERISTIC(.*?)/end\s+DEF_CHARACTERISTIC', re.DOTALL | re.IGNORECASE)
    in_meas_pattern = re.compile(r'/begin\s+IN_MEASUREMENT(.*?)/end\s+IN_MEASUREMENT', re.DOTALL | re.IGNORECASE)
    ref_char_pattern = re.compile(r'/begin\s+REF_CHARACTERISTIC(.*?)/end\s+REF_CHARACTERISTIC', re.DOTALL | re.IGNORECASE)
    name_pattern = re.compile(r'([A-Za-z_]\w*)')
    
    for func_match in func_pattern.finditer(content):
        func_name = func_match.group(1)
        func_body = func_match.group(2)
        
        var_names = []
        # DEF_CHARACTERISTIC 中的变量
        for dc_match in def_char_pattern.finditer(func_body):
            for n in name_pattern.finditer(dc_match.group(1)):
                var_names.append(n.group(1))
        # REF_CHARACTERISTIC 中的变量（轴引用）
        for rc_match in ref_char_pattern.finditer(func_body):
            for n in name_pattern.finditer(rc_match.group(1)):
                var_names.append(n.group(1))
        # IN_MEASUREMENT 中的变量
        for im_match in in_meas_pattern.finditer(func_body):
            for n in name_pattern.finditer(im_match.group(1)):
                var_names.append(n.group(1))
        
        if var_names:
            functions[func_name] = var_names
    
    # 解析CHARACTERISTIC块
    objects = []
    cms = {}
    
    # 正则表达式 - 支持名称在/begin行或下一行注释中
    char_pattern = re.compile(
        r'/begin\s+CHARACTERISTIC\s*(?:\n\s*/\*\s*Name\s*\*/\s*(\w+)|(\w+))\s*\n'
        r'(.*?)/end\s+CHARACTERISTIC',
        re.DOTALL | re.IGNORECASE
    )
    addr_pattern = re.compile(r'ECU_ADDRESS\s+0[xX]([0-9A-Fa-f]+)', re.IGNORECASE)
    addr_comment_pattern = re.compile(r'/\*\s*ECU\s+Address\s*\*/\s*0[xX]([0-9A-Fa-f]+)', re.IGNORECASE)
    type_pattern = re.compile(r'(?:Characteristic\s+Type|Type)\s*\*/\s*(\w+)', re.IGNORECASE)
    layout_pattern = re.compile(r'Record\s+Layout\s*\*/\s*(\w+)', re.IGNORECASE)
    cm_pattern = re.compile(r'Conversion\s+[Mm]ethod\s*\*/\s*(\w+)', re.IGNORECASE)
    longid_pattern = re.compile(r'"([^"]*)"')
    
    # COMPU_METHOD 解析 - 支持名称在/begin行或下一行注释中
    compu_pattern = re.compile(
        r'/begin\s+COMPU_METHOD\s*(?:\n\s*/\*\s*Name\s*(?:of\s+CompuMethod)?\s*\*/\s*(\w+)|(\w+))\s*\n'
        r'(.*?)/end\s+COMPU_METHOD',
        re.DOTALL | re.IGNORECASE
    )
    conv_pattern = re.compile(r'Conversion\s+Type\s*\*/\s*(\w+)', re.IGNORECASE)
    coeffs_pattern = re.compile(r'COEFFS(?:_LINEAR)?\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)')
    byte_order_pattern = re.compile(r'BYTE_ORDER\s+(\w+)', re.IGNORECASE)
    
    # AXIS_DESCR 解析
    axis_descr_pattern = re.compile(r'/begin\s+AXIS_DESCR(.*?)/end\s+AXIS_DESCR', re.DOTALL | re.IGNORECASE)
    axis_type_pattern = re.compile(r'Axis\s+Type\s*\*/\s*(\w+)', re.IGNORECASE)
    axis_ref_pattern = re.compile(r'AXIS_PTS_REF\s+(\w+)', re.IGNORECASE)
    axis_n_pattern = re.compile(r'Number\s+of\s+Axis\s+Pts\s*\*/\s*(\d+)', re.IGNORECASE)
    
    # 先解析COMPU_METHOD
    for cm_match in compu_pattern.finditer(content):
        cm_name = cm_match.group(1) or cm_match.group(2)
        cm_body = cm_match.group(3)
        
        cm_info = {'conv': None, 'coeffs': None, 'byte_order': None}
        m = conv_pattern.search(cm_body)
        if m:
            cm_info['conv'] = m.group(1)
        m = coeffs_pattern.search(cm_body)
        if m:
            cm_info['coeffs'] = tuple(float(x) for x in m.groups())
        m = byte_order_pattern.search(cm_body)
        if m:
            cm_info['byte_order'] = m.group(1)
        cms[cm_name] = cm_info
    
    # 解析AXIS_PTS块，建立轴引用映射
    axis_pts_map = {}
    axis_pts_pattern = re.compile(
        r'/begin\s+AXIS_PTS\s*(?:\n\s*/\*\s*Name\s*\*/\s*(\w+)|(\w+))\s*\n'
        r'(.*?)/end\s+AXIS_PTS',
        re.DOTALL | re.IGNORECASE
    )
    for axis_match in axis_pts_pattern.finditer(content):
        axis_name = axis_match.group(1) or axis_match.group(2)
        axis_body = axis_match.group(3)
        
        axis_info = {'name': axis_name, 'addr': None, 'data_type': None, 'cm': None, 'n': 0}
        
        # 地址
        m = addr_pattern.search(axis_body)
        if not m:
            m = addr_comment_pattern.search(axis_body)
        if m:
            axis_info['addr'] = int(m.group(1), 16)
        
        # 数据类型
        m = layout_pattern.search(axis_body)
        if m:
            axis_info['data_type'] = m.group(1)
        
        # 转换方法
        m = cm_pattern.search(axis_body)
        if m:
            axis_info['cm'] = m.group(1)
        
        # 点数
        m = re.search(r'Number\s+of\s+Axis\s+Pts\s*\*/\s*(\d+)', axis_body, re.IGNORECASE)
        if m:
            axis_info['n'] = int(m.group(1))
        
        axis_pts_map[axis_name] = axis_info
    
    # 解析FIX_AXIS块
    fix_axis_pattern = re.compile(
        r'/begin\s+FIX_AXIS\s*(?:\n\s*/\*\s*Name\s*\*/\s*(\w+)|(\w+))\s*\n'
        r'(.*?)/end\s+FIX_AXIS',
        re.DOTALL | re.IGNORECASE
    )
    for axis_match in fix_axis_pattern.finditer(content):
        axis_name = axis_match.group(1) or axis_match.group(2)
        axis_body = axis_match.group(3)
        
        axis_info = {'name': axis_name, 'addr': None, 'data_type': None, 'cm': None, 'n': 0}
        
        # 数据类型
        m = layout_pattern.search(axis_body)
        if m:
            axis_info['data_type'] = m.group(1)
        
        # 转换方法
        m = cm_pattern.search(axis_body)
        if m:
            axis_info['cm'] = m.group(1)
        
        # 点数
        m = re.search(r'Number\s+of\s+Axis\s+Pts\s*\*/\s*(\d+)', axis_body, re.IGNORECASE)
        if m:
            axis_info['n'] = int(m.group(1))
        
        axis_pts_map[axis_name] = axis_info
    
    # 解析CHARACTERISTIC
    for char_match in char_pattern.finditer(content):
        # 名称可能在group(1)（注释格式）或group(2）（直接格式）
        char_name = char_match.group(1) or char_match.group(2)
        char_body = char_match.group(3)
        
        obj = {
            'name': char_name,
            'addr': None,
            'data_type': None,
            'cm': None,
            'char_type': None,
            'function': None,
            'longid': '',
            'axes': [],
        }
        
        # 地址 - 支持两种格式
        m = addr_pattern.search(char_body)
        if not m:
            m = addr_comment_pattern.search(char_body)
        if m:
            obj['addr'] = int(m.group(1), 16)
        
        # 数据类型 (从Record Layout推断)
        m = layout_pattern.search(char_body)
        if m:
            obj['data_type'] = m.group(1)
        
        # 转换方法
        m = cm_pattern.search(char_body)
        if m:
            obj['cm'] = m.group(1)
        
        # Characteristic Type
        m = type_pattern.search(char_body)
        if m:
            obj['char_type'] = m.group(1)
        
        # 解析数组大小（VAL_BLK类型的NUMBER字段）
        m = re.search(r'NUMBER\s+(\d+)', char_body, re.IGNORECASE)
        if m:
            obj['array_size'] = int(m.group(1))
        else:
            obj['array_size'] = 1
        
        # 长标识
        m = longid_pattern.search(char_body)
        if m:
            obj['longid'] = m.group(1)
        
        # AXIS_DESCR
        for axis_match in axis_descr_pattern.finditer(char_body):
            axis_body = axis_match.group(1)
            ax = {'type': None, 'cm': None, 'ref': None, 'n': 0, 'addr': None, 'data_type': None}
            m = axis_type_pattern.search(axis_body)
            if m:
                ax['type'] = m.group(1)
            m = cm_pattern.search(axis_body)
            if m:
                ax['cm'] = m.group(1)
            m = axis_ref_pattern.search(axis_body)
            if m:
                ax['ref'] = m.group(1)
            m = axis_n_pattern.search(axis_body)
            if m:
                ax['n'] = int(m.group(1))
            
            # 关联AXIS_PTS信息
            if ax['ref'] and ax['ref'] in axis_pts_map:
                axis_pts = axis_pts_map[ax['ref']]
                ax['addr'] = axis_pts['addr']
                ax['data_type'] = axis_pts['data_type']
                if not ax['cm']:
                    ax['cm'] = axis_pts['cm']
                if ax['n'] == 0:
                    ax['n'] = axis_pts['n']
            
            obj['axes'].append(ax)
        
        # 找出所属FUNCTION
        for func_name, var_names in functions.items():
            if char_name in var_names:
                obj['function'] = func_name
                break
        
        objects.append(obj)
    
    # 创建变量名到FUNCTION的反向映射
    var_to_func = {}
    for func_name, var_names in functions.items():
        for var_name in var_names:
            var_to_func[var_name] = func_name
    
    return {
        'objects': objects,
        'cms': cms,
        'functions': functions,
        'var_to_func': var_to_func,
    }


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


def update_a2l_file(a2l_path, symbols, out_path, remove_unmatched=False):
    """根据符号表更新 A2L 中变量的 ECU 地址 (按变量名精确匹配).
    remove_unmatched=True 时删除符号表中没有的变量块.
    返回 (total, matched, updated, elf_only_vars, stats);
    stats: {'unchanged': 地址未变, 'unmatched': 未匹配数, 'removed_count': 已删除块数}
    """
    variables, lines = extract_a2l_variables(a2l_path)
    total = len(variables)

    matched = updated = unchanged = removed = 0
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
             'removed_count': removed}
    return total, matched, updated, elf_only, stats


def insert_into_header(header_path, record_lines, variable_blocks, compu_lines, file_var_map, output_path):
    """将提取的内容插入头文件的 Data 标记处"""
    with open(header_path, 'r', encoding='utf-8', errors='ignore') as f:
        header_lines = f.readlines()
    
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
            record_lines, variable_blocks, compu_lines, file_var_map, file_count = extract_a2l_content(path)
            print(f"文件数: {file_count}")
            print(f"变量块: {len(variable_blocks)}")
            print(f"RECORD_LAYOUT: {len(record_lines)}")
            print(f"COMPU_METHOD: {len(compu_lines)}")
        else:
            variables, _ = extract_a2l_variables(path)
            print(f"变量数: {len(variables)}")
            for v in variables[:10]:
                print(f"  {v['name']:40s} 行{v['addr_line']}")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)