#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ELF 文件解析模块 - 提取变量符号地址"""

import struct


def parse_elf_symbols(elf_path):
    """解析 ELF 文件，提取变量符号地址"""
    with open(elf_path, 'rb') as f:
        data = f.read()
    
    if data[:4] != b'\x7fELF':
        raise ValueError("不是有效的 ELF 文件")
    
    ei_class = data[4]
    
    if ei_class == 2:
        e_shoff = struct.unpack_from('<Q', data, 40)[0]
        e_shentsize = struct.unpack_from('<H', data, 58)[0]
        e_shnum = struct.unpack_from('<H', data, 60)[0]
        e_shstrndx = struct.unpack_from('<H', data, 62)[0]
        is_64 = True
    else:
        e_shoff = struct.unpack_from('<I', data, 32)[0]
        e_shentsize = struct.unpack_from('<H', data, 46)[0]
        e_shnum = struct.unpack_from('<H', data, 48)[0]
        e_shstrndx = struct.unpack_from('<H', data, 50)[0]
        is_64 = False
    
    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        if is_64:
            sh = struct.unpack_from('<IIQQQQIIQQ', data, off)
        else:
            sh = struct.unpack_from('<IIIIIIIIII', data, off)
        sections.append({
            'sh_name': sh[0], 'sh_type': sh[1], 'sh_flags': sh[2],
            'sh_addr': sh[3], 'sh_offset': sh[4], 'sh_size': sh[5],
            'sh_link': sh[6], 'sh_info': sh[7], 'sh_addralign': sh[8],
            'sh_entsize': sh[9]
        })
    
    shstrtab = sections[e_shstrndx]
    shstr_data = data[shstrtab['sh_offset']:shstrtab['sh_offset']+shstrtab['sh_size']]
    
    def get_str(tab, off):
        end = tab.find(b'\x00', off)
        if end == -1:
            return tab[off:].decode('ascii', errors='replace')
        return tab[off:end].decode('ascii', errors='replace')
    
    symtab = None
    for sec in sections:
        if get_str(shstr_data, sec['sh_name']) == '.symtab':
            symtab = sec
            break
    if symtab is None:
        for sec in sections:
            if get_str(shstr_data, sec['sh_name']) == '.dynsym':
                symtab = sec
                break
    if symtab is None:
        raise ValueError("ELF 中未找到 .symtab 符号表")
    
    strtab = sections[symtab['sh_link']]
    strtab_data = data[strtab['sh_offset']:strtab['sh_offset']+strtab['sh_size']]
    
    symbols = {}
    entry_size = 24 if is_64 else 16
    n = symtab['sh_size'] // entry_size
    
    for i in range(n):
        off = symtab['sh_offset'] + i * entry_size
        if is_64:
            st_name, st_info, st_other, st_shndx, st_value, st_size = \
                struct.unpack_from('<IBBHQQ', data, off)
        else:
            st_name, st_value, st_size, st_info, st_other, st_shndx = \
                struct.unpack_from('<IIIBBH', data, off)
        
        if st_name == 0:
            continue
        
        name = get_str(strtab_data, st_name)
        if not name:
            continue
        
        # 只保留符号类型和绑定信息
        st_type = st_info & 0xf
        st_bind = st_info >> 4
        
        # 只处理 NOTYPE, OBJECT, FUNC 类型
        if st_type not in (0, 1, 2):
            continue
        
        # 只处理 GLOBAL, WEAK 绑定
        if st_bind not in (1, 2):
            continue
        
        # 排除空值和特殊段
        if st_value == 0 or st_shndx == 0:
            continue
        
        symbols[name] = st_value
    
    return symbols


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python elf_parser.py <elf_file>")
        sys.exit(1)
    
    try:
        symbols = parse_elf_symbols(sys.argv[1])
        print(f"符号数: {len(symbols)}")
        for name, addr in list(symbols.items())[:20]:
            print(f"  {name:40s} 0x{addr:08X}")
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)