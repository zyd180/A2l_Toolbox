#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A2L 三件套回归: 地址映射 / 合并 / 模型版本同步.

同步部分的断言针对真实踩过的坑: 同名对象必须以新版内容更新但**保留整车真实地址**;
旧版遗留对象按 CM 前缀归属安全删除; 其他模型的对象一个字节都不许动.
"""

import os
import re

import _harness  # noqa: F401
import fixtures
from core.a2l_parser import (extract_a2l_variables, update_a2l_file,
                             extract_a2l_content, write_content_only,
                             insert_into_header, get_a2l_blocks)
from core.sync_engine import sync_model_a2l, _parse_blocks
from core.map_parser import parse_map_ownership


_CM = """    /begin COMPU_METHOD
      /* Name of CompuMethod    */      {name}
      /* Long identifier        */      "Q = V"
      /* Conversion Type        */      RAT_FUNC
      /* Format                 */      "%3.0"
      /* Units                  */      ""
      /* Coefficients           */      COEFFS 0 1 0 0 0 1
    /end COMPU_METHOD
"""

_LAYOUT = """    /begin RECORD_LAYOUT Scalar_UWORD
      FNC_VALUES  1 UWORD COLUMN_DIR DIRECT
    /end RECORD_LAYOUT
"""

_CHAR = """    /begin CHARACTERISTIC
      /* Name                   */      {name}
      /* Long Identifier        */      "sig"
      /* Characteristic Type    */      VALUE
      /* ECU Address            */      {addr}
      /* Record Layout          */      Scalar_UWORD
      /* Maxdiff                */      0
      /* Conversion Method      */      {cm}
      /* Lower Limit            */      0
      /* Upper Limit            */      {upper}
    /end CHARACTERISTIC
"""

# 地址行的另一种合法写法 (ASAP2 标准关键字形式)
_CHAR_KW = _CHAR.replace('      /* ECU Address            */      {addr}',
                         '      ECU_ADDRESS {addr}')


def _a2l(blocks):
    return ('ASAP2_VERSION 1 61\n/begin PROJECT P "p"\n  /begin MODULE M "m"\n'
            + ''.join(blocks) + '  /end MODULE\n/end PROJECT\n')


# 带 Simulink 模型声明的模型级 A2L 模板 (归属判定要读 "Code generation for model")
_MODEL_A2L = '''/******************************************************************************
 * Code generation for model "{model}".
 ******************************************************************************/

ASAP2_VERSION 1 61

/begin PROJECT ProjectName "p"

  /begin MODULE ModuleName "m"

    /begin COMPU_METHOD
      /* Name of CompuMethod    */      {cm}
      /* Long identifier        */      "Q = V"
      /* Conversion Type        */      RAT_FUNC
      /* Format                 */      "%3.0"
      /* Units                  */      ""
      /* Coefficients           */      COEFFS 0 1 0 0 0 1
    /end COMPU_METHOD

    /begin RECORD_LAYOUT Scalar_UWORD
      FNC_VALUES  1 UWORD COLUMN_DIR DIRECT
    /end RECORD_LAYOUT

    /begin CHARACTERISTIC
      /* Name                   */      {name}
      /* Long Identifier        */      "{longid}"
      /* Characteristic Type    */      VALUE
      /* ECU Address            */      0x00000000
      /* Record Layout          */      Scalar_UWORD
      /* Maxdiff                */      0
      /* Conversion Method      */      {cm}
      /* Lower Limit            */      0
      /* Upper Limit            */      {upper}
    /end CHARACTERISTIC

  /end MODULE

/end PROJECT
'''

# MAP 符号行: 第 5 列符号名, 最后一列定义它的 .o
_MAP_LINE = '0x80400000 0x80400000  1 g {sym}  PF1_Cal  .rodata  ASW\\code\\{obj}.o\n'


def _merged_upper(path, name):
    """读合并产物里某对象的 Upper Limit; 找不到返回 'NOT_FOUND'"""
    for b in get_a2l_blocks(path):
        if b.get('name') == name:
            m = re.search(r'Upper [Ll]imit\s*\*/\s*([-\d.]+)', ''.join(b['lines']))
            return float(m.group(1)) if m else None
    return 'NOT_FOUND'


def _dedup_case(suite, tmp, tag, obj_name, map_owner, expect_upper, expect_reason_key,
                model_b='MDL_B'):
    """构造两个模型 A2L 声明同一对象(限值不同) + 可选 MAP, 断言保留哪一份"""
    d = os.path.join(tmp, 'dedup_%s' % tag)
    os.makedirs(d, exist_ok=True)
    _write(os.path.join(d, 'MDL_A.a2l'),
           _MODEL_A2L.format(model='MDL_A', cm='MDL_A_CM_u', name=obj_name,
                             longid='from A', upper='3.0'))
    _write(os.path.join(d, '%s.a2l' % model_b),
           _MODEL_A2L.format(model=model_b, cm='%s_CM_u' % model_b, name=obj_name,
                             longid='from B', upper='255.0'))
    mp = None
    if map_owner:
        mp = _write(os.path.join(tmp, 'map_%s.map' % tag),
                    _MAP_LINE.format(sym=obj_name + '_MP', obj=map_owner))
    rec, vb, compu, fmap, n, dedup = extract_a2l_content(d, recursive=False,
                                                         map_path=mp,
                                                         log=lambda m: None)
    out = os.path.join(tmp, 'dedup_%s.a2l' % tag)
    write_content_only(rec, vb, compu, fmap, out)
    suite.eq('[%s] 同名对象只剩 1 块' % tag, len(vb), 1)
    suite.eq('[%s] 保留的限值' % tag, _merged_upper(out, obj_name), expect_upper)
    suite.eq('[%s] 裁决依据计数' % tag, dedup[expect_reason_key], 1)
    return dedup


def _sync_src():
    return _a2l([
        _CM.format(name='MDL_CM_u'),
        _LAYOUT,
        _CHAR.format(name='MDL_Sig', addr='0x0000', cm='MDL_CM_u', upper='9'),
        _CHAR.format(name='MDL_New', addr='0x0000', cm='MDL_CM_u', upper='7'),
    ])


def _sync_tgt():
    return _a2l([
        _CM.format(name='MDL_CM_u'),
        _CM.format(name='OTH_CM_u'),
        _LAYOUT,
        _CHAR.format(name='MDL_Sig', addr='0x00002000', cm='MDL_CM_u', upper='5'),
        _CHAR.format(name='MDL_Old', addr='0x00002010', cm='MDL_CM_u', upper='5'),
        _CHAR.format(name='OTH_Sig', addr='0x00003000', cm='OTH_CM_u', upper='5'),
    ])


def _write(path, text):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    return path


def run(suite):
    tmp = suite.tmpdir()

    # ==================== 地址映射 ====================
    a2l, hex_path = fixtures.write_fixture(os.path.join(tmp, 'addr'))
    out = os.path.join(tmp, 'addr_out.a2l')
    symbols = {'Sca_Val': 0x3000}
    total, matched, updated, elf_only, stats = update_a2l_file(a2l, symbols, out)
    suite.eq('地址映射 变量总数 (5 CHARACTERISTIC + 3 AXIS_PTS)', total, 8)
    suite.eq('地址映射 匹配数', matched, 1)
    suite.eq('地址映射 更新数', updated, 1)
    suite.eq('地址映射 未匹配数', stats['unmatched'], 7)

    text = open(out, encoding='utf-8').read()
    suite.check('目标变量地址被替换为 0x00003000', '0x00003000' in text, '')
    suite.check('仅替换一处地址', text.count('0x00003000') == 1,
                '出现 %d 次' % text.count('0x00003000'))
    _, lines = extract_a2l_variables(out)
    suite.check('其他对象地址保持原值', '0x00001014' in ''.join(lines), '')

    out_rm = os.path.join(tmp, 'addr_rm.a2l')
    update_a2l_file(a2l, symbols, out_rm, remove_unmatched=True)
    left, _ = extract_a2l_variables(out_rm)
    suite.eq('删除未匹配后仅剩 1 个变量', [v['name'] for v in left], ['Sca_Val'])

    # ---- only_missing: 只填空位, 不覆盖已有真实地址 ----
    # 专用小夹具: A_Has 已带真实地址, B_Empty 是 0x0000 占位
    partial = _write(os.path.join(tmp, 'addr_partial.a2l'), _a2l([
        _CM.format(name='MDL_CM_u'), _LAYOUT,
        _CHAR.format(name='A_Has', addr='0x80401234', cm='MDL_CM_u', upper='9'),
        _CHAR.format(name='B_Empty', addr='0x00000000', cm='MDL_CM_u', upper='9'),
    ]))
    syms2 = {'A_Has': 0x3000, 'B_Empty': 0x4000}
    out_keep = os.path.join(tmp, 'addr_keep.a2l')
    _t, _m, upd_keep, _o, st_keep = update_a2l_file(partial, syms2, out_keep,
                                                    only_missing=True)
    ktxt = open(out_keep, encoding='utf-8').read()
    suite.check('only_missing 保留已有真实地址', '0x80401234' in ktxt and
                '0x00003000' not in ktxt, '')
    suite.check('only_missing 仍填补 0x0000 占位', '0x00004000' in ktxt, '')
    suite.eq('only_missing 更新数', upd_keep, 1)
    suite.eq('only_missing 统计保留数', st_keep['kept_existing'], 1)

    out_all = os.path.join(tmp, 'addr_all.a2l')
    update_a2l_file(partial, syms2, out_all)
    atxt = open(out_all, encoding='utf-8').read()
    suite.check('默认模式会覆盖已有地址',
                '0x00003000' in atxt and '0x80401234' not in atxt, '')

    # ==================== 合并 ====================
    folder = os.path.join(tmp, 'merge')
    os.makedirs(folder)
    for fn in ('a.a2l', 'b.a2l'):
        _write(os.path.join(folder, fn), fixtures.a2l_text())
    rec, var_blocks, compu, fmap, n_file, dedup = extract_a2l_content(folder, recursive=False)
    suite.eq('合并 文件数', n_file, 2)
    # 两个文件内容完全相同: 8 个对象各声明两次, 去重后保留 8 个
    suite.eq('合并 同名对象去重后块数', len(var_blocks), 8)
    suite.eq('合并 去重组数', dedup['duplicated'], 8)
    suite.eq('合并 等价副本按内容等价处理', dedup['by_equal'], 8)
    suite.eq('合并 等价副本不产生结构差异', len(dedup['conflicts']), 0)
    # RECORD_LAYOUT 必须被提取并按名去重 (曾因只认 /* Name */ 注释而整批丢失)
    suite.eq('合并 RECORD_LAYOUT 按名去重', len(rec), len(fixtures.LAYOUTS))
    suite.eq('合并 COMPU_METHOD 按名去重', len(compu), len(fixtures.CMS))
    suite.eq('合并 按文件分组', sorted(fmap), ['a', 'b'])

    merged = os.path.join(tmp, 'merged.a2l')
    write_content_only(rec, var_blocks, compu, fmap, merged)
    mtxt = open(merged, encoding='utf-8').read()
    suite.check('纯内容输出含 FUNCTION', '/begin FUNCTION' in mtxt, '')
    suite.check('纯内容输出不含 MODULE 外壳', '/begin MODULE' not in mtxt, '')

    # 缩进不得叠加: 顶层块头固定 4 空格 (曾无条件加 4, 原缩进之上再叠一层 -> 产物虚胖 1.8MB)
    top = ('CHARACTERISTIC', 'MEASUREMENT', 'AXIS_PTS', 'COMPU_METHOD', 'RECORD_LAYOUT')
    heads = [len(l) - len(l.lstrip(' ')) for l in mtxt.splitlines()
             if l.lstrip().startswith('/begin')
             and l.split()[1] in top]
    suite.eq('顶层块头缩进统一为 4 空格', sorted(set(heads)), [4])
    nested = [len(l) - len(l.lstrip(' ')) for l in mtxt.splitlines()
              if l.lstrip().startswith('/begin AXIS_DESCR')]
    suite.eq('嵌套 AXIS_DESCR 保持相对层级 (6 空格)', sorted(set(nested)), [6])
    inner = [len(l) - len(l.lstrip(' ')) for l in mtxt.splitlines()
             if l.lstrip().startswith('/* Name')]
    suite.eq('块内字段缩进为 6 空格', sorted(set(inner)), [6])

    # 生成器残留标注 /* @ECU_Address@Name@ */ 必须剥除:
    # 标注名与 /* Name */ 重复 (实测 44535 个块 0 例不同), 且它是 C 注释,
    # ASAP2/INCA 解析器一律跳过 -> 纯冗余, 实测占 1.7MB
    ann_dir = os.path.join(tmp, 'ann')
    os.makedirs(ann_dir)
    _write(os.path.join(ann_dir, 'ann.a2l'),
           'ASAP2_VERSION 1 61\n/begin PROJECT P "p"\n  /begin MODULE M "m"\n'
           '    /begin CHARACTERISTIC\n'
           '      /* Name                   */      Ann_Sig\n'
           '      /* Long Identifier        */      "sig"\n'
           '      /* Type                   */      VALUE\n'
           '      /* ECU Address            */      0x0000 /* @ECU_Address@Ann_Sig@ */\n'
           '      /* Record Layout          */      Scalar_ULONG\n'
           '      /* Conversion Method      */      Ann_CM_u\n'
           '      /* Lower Limit            */      0\n'
           '      /* Upper Limit            */      255\n'
           '    /end CHARACTERISTIC\n'
           '  /end MODULE\n/end PROJECT\n')
    _ar, ann_blocks, _ac, _af, _an, _ad = extract_a2l_content(ann_dir, recursive=False)
    suite.eq('标注: 块仍被提取', len(ann_blocks), 1)
    suite.check('标注: 产物已剥除 @ECU_Address@',
                '@ECU_Address@' not in ann_blocks[0], ann_blocks[0][:160])
    suite.check('标注: 地址字段保留', '0x0000' in ann_blocks[0], '')
    suite.check('标注: 名字未受影响', 'Ann_Sig' in ann_blocks[0], '')
    suite.check('标注: 行尾无残留空白',
                all(not l.endswith(' ') for l in ann_blocks[0].splitlines()), '')

    header = _write(os.path.join(tmp, 'header.a2l'),
                    'ASAP2_VERSION 1 61\n/begin PROJECT P "p"\n  /begin MODULE M "m"\n'
                    '/* * * * * * * * * * * * * * * Data * * * * * * * * * * * * * * */\n'
                    '  /end MODULE\n/end PROJECT\n')
    with_header = os.path.join(tmp, 'with_header.a2l')
    insert_into_header(header, rec, var_blocks, compu, fmap, with_header)
    htxt = open(with_header, encoding='utf-8').read()
    suite.check('头文件模式保留外壳', '/begin PROJECT' in htxt and '/end MODULE' in htxt, '')
    suite.check('头文件模式只保留一个 /end MODULE',
                htxt.count('/end MODULE') == 1, '出现 %d 次' % htxt.count('/end MODULE'))
    suite.check('头文件模式内容在标记之后',
                htxt.index('Data *') < htxt.index('/begin CHARACTERISTIC'), '')

    # 头文件已带标准布局时, 合并内容不得重复定义同名结构/转换方法
    header2 = _write(os.path.join(tmp, 'header2.a2l'),
                     'ASAP2_VERSION 1 61\n/begin PROJECT P "p"\n  /begin MODULE M "m"\n'
                     + _LAYOUT + _CM.format(name='T_CM_Uint') +
                     '/* * * * * * * * * * * * * * * Data * * * * * * * * * * * * * * */\n'
                     '  /end MODULE\n/end PROJECT\n')
    out2 = os.path.join(tmp, 'with_header2.a2l')
    insert_into_header(header2, rec, var_blocks, compu, fmap, out2,
                       log=lambda m: None)
    h2 = open(out2, encoding='utf-8').read()
    suite.eq('头文件已定义的布局不重复写入',
             len(re.findall(r'/begin RECORD_LAYOUT\s+Scalar_UWORD', h2)), 1)
    suite.eq('头文件未定义的布局仍然写入',
             len(re.findall(r'/begin RECORD_LAYOUT\s+Lookup2D_UWORD', h2)), 1)
    suite.eq('头文件已定义的转换方法不重复写入',
             len(re.findall(r'/\*\s*Name of CompuMethod\s*\*/\s+T_CM_Uint', h2)), 1)
    suite.eq('未定义的转换方法仍然写入',
             len(re.findall(r'/\*\s*Name of CompuMethod\s*\*/\s+T_CM_x10', h2)), 1)

    # ---- 同名对象归属: 按 MAP 定义模块 / 前缀 / 限值 三条路径 ----
    # 两个模型都声明 SIG_X, 但限值不同 (定义方 3.0 = 枚举范围, 引用方 255.0 = uint8 兜底)
    _dedup_case(suite, tmp, 'map_A', 'SIG_X', 'MDL_A', 3.0, 'by_map')
    # MAP 指向引用方时必须服从 MAP (证明优先级高于"限值更紧")
    _dedup_case(suite, tmp, 'map_B', 'SIG_X', 'MDL_B', 255.0, 'by_map')
    # 无 MAP: 退化为"限值更紧", 仍拿到 3.0 而不是 255.0
    _dedup_case(suite, tmp, 'no_map', 'SIG_X', None, 3.0, 'by_limit')
    # 无 MAP 且名称前缀只命中一个模型: 按前缀
    _dedup_case(suite, tmp, 'prefix', 'MDL_A_Sig', None, 3.0, 'by_prefix',
                model_b='ZZZ_B')

    # ---- 仅数字写法/地址标注不同, 不得判为结构冲突 ----
    # 生成器差异: 4294967295 vs 4.294967295E+9、0 vs 0.0、带不带 @ECU_Address@ 标注
    d = os.path.join(tmp, 'dedup_fmt')
    os.makedirs(d, exist_ok=True)
    tpl = dict(name='SIG_Y', longid='same')
    a_txt = _MODEL_A2L.format(model='MDL_P', cm='MDL_P_CM_u', upper='4294967295', **tpl)
    b_txt = _MODEL_A2L.format(model='MDL_Q', cm='MDL_Q_CM_u', upper='4.294967295E+9', **tpl)
    b_txt = b_txt.replace('Lower Limit            */      0',
                          'Lower Limit            */      0.0')
    b_txt = b_txt.replace('/* ECU Address            */      0x00000000',
                          '/* ECU Address            */      0x00000000 '
                          '/* @ECU_Address@SIG_Y@ */')
    _write(os.path.join(d, 'MDL_P.a2l'), a_txt)
    _write(os.path.join(d, 'MDL_Q.a2l'), b_txt)
    rec_f, vb_f, compu_f, fmap_f, n_f, dedup_f = extract_a2l_content(
        d, recursive=False, log=lambda m: None)
    out_f = os.path.join(tmp, 'dedup_fmt.a2l')
    write_content_only(rec_f, vb_f, compu_f, fmap_f, out_f)
    suite.eq('[fmt] 只剩 1 块', len(vb_f), 1)
    suite.eq('[fmt] 判为内容等价', dedup_f['by_equal'], 1)
    suite.eq('[fmt] 不产生结构冲突', len(dedup_f['conflicts']), 0)

    # ==================== 模型版本同步 ====================
    src = _write(os.path.join(tmp, 'src.a2l'), _sync_src())
    tgt = _write(os.path.join(tmp, 'tgt.a2l'), _sync_tgt())
    sync_out = os.path.join(tmp, 'synced.a2l')
    st = sync_model_a2l(src, tgt, sync_out, purge=True, backup=False,
                        log=lambda m: None)
    # 替换含同名 COMPU_METHOD + 同名 RECORD_LAYOUT 的整体更新, 故为 3 而非 1
    suite.eq('同步 替换/更新数 (对象+CM+LAYOUT)', st['replaced'], 3)
    suite.eq('同步 新增数', st['added'], 1)
    suite.eq('同步 删除数', st['deleted'], 1)

    # 源模型 A2L 带生成器残留标注时, 同步不得把它灌进整车 A2L
    # (实测: 4 个模型同步会给整车 A2L 灌进 9718 条无用标注)
    ann_src = _write(os.path.join(tmp, 'src_ann.a2l'),
                     _sync_src().replace('0x0000\n',
                                         '0x0000 /* @ECU_Address@MDL_Sig@ */\n'))
    ann_tgt = _write(os.path.join(tmp, 'tgt_ann.a2l'), _sync_tgt())
    ann_out = os.path.join(tmp, 'synced_ann.a2l')
    sync_model_a2l(ann_src, ann_tgt, ann_out, purge=False, backup=False,
                   log=lambda m: None)
    ann_txt = open(ann_out, encoding='utf-8').read()
    suite.check('同步 剥除源侧 @ECU_Address@ 标注',
                '@ECU_Address@' not in ann_txt,
                ann_txt[max(0, ann_txt.find('@ECU_Address@') - 50):][:110])
    suite.check('同步 剥除后整车地址仍被保留', '0x00002000' in ann_txt, '')

    # ---- 归属裁决: 本文件只是引用方时, 不得覆盖目标里定义方的那一份 ----
    # 场景: MDL_A 声明 SIG_Z 上限 255.0 (uint8 兜底), MAP 显示它由 OTH_MDL 定义,
    # 而整车 A2L 里已有定义方的 3.0 版本 -> 不能把标定上限放宽
    ref_src = _write(os.path.join(tmp, 'ref_src.a2l'),
                     '/* Code generation for model "MDL_A" */\n'
                     + _a2l([_CM.format(name='MDL_A_CM_u'), _LAYOUT,
                             _CHAR.format(name='SIG_Z', addr='0x0000',
                                          cm='MDL_A_CM_u', upper='255.0')]))
    ref_tgt = _write(os.path.join(tmp, 'ref_tgt.a2l'),
                     _a2l([_CM.format(name='OTH_CM_u'), _LAYOUT,
                           _CHAR.format(name='SIG_Z', addr='0x00003000',
                                        cm='OTH_CM_u', upper='3.0')]))
    own_map = parse_map_ownership(_write(
        os.path.join(tmp, 'own.map'), _MAP_LINE.format(sym='SIG_Z_E', obj='OTH_MDL')))

    out_ref = os.path.join(tmp, 'ref_out.a2l')
    st_ref = sync_model_a2l(ref_src, ref_tgt, out_ref, purge=False, backup=False,
                            log=lambda m: None, owner_map=own_map)
    suite.eq('归属裁决 记为引用方并跳过', st_ref['skipped_ref'], 1)
    suite.check('归属裁决 定义方上限 3.0 未被引用方 255.0 覆盖',
                _merged_upper(out_ref, 'SIG_Z') == 3.0,
                '实际 %s' % _merged_upper(out_ref, 'SIG_Z'))
    suite.check('归属裁决 目标地址未被改动', '0x00003000' in open(
        out_ref, encoding='utf-8').read(), '')

    # 不给 MAP 时无从判断定义方, 仍按旧行为覆盖 (记录降级语义, 防止静默变化)
    out_nomap = os.path.join(tmp, 'ref_out_nomap.a2l')
    st_nomap = sync_model_a2l(ref_src, ref_tgt, out_nomap, purge=False, backup=False,
                              log=lambda m: None)
    suite.eq('无 MAP 时不跳过', st_nomap['skipped_ref'], 0)
    suite.check('无 MAP 时按新版覆盖 (降级行为)', _merged_upper(out_nomap, 'SIG_Z') == 255.0,
                '实际 %s' % _merged_upper(out_nomap, 'SIG_Z'))

    # MAP 判定定义方就是本模型: 必须正常更新, 不能被误跳过
    own_map_self = parse_map_ownership(_write(
        os.path.join(tmp, 'own_self.map'), _MAP_LINE.format(sym='SIG_Z_E', obj='MDL_A')))
    out_self = os.path.join(tmp, 'ref_out_self.a2l')
    st_self = sync_model_a2l(ref_src, ref_tgt, out_self, purge=False, backup=False,
                             log=lambda m: None, owner_map=own_map_self)
    suite.eq('定义方是本模型时不跳过', st_self['skipped_ref'], 0)
    suite.check('定义方是本模型时正常更新上限', _merged_upper(out_self, 'SIG_Z') == 255.0,
                '实际 %s' % _merged_upper(out_self, 'SIG_Z'))

    # ---- 清理: 归属以 MAP 定义方为准, 不再只看 CM 前缀 ----
    # 场景: 模型内部子系统改过名 (旧 OLDSUB_CM_* -> 新 MDL_M_CM_*), 老对象挂的仍是旧前缀.
    # 只看 CM 前缀会一个也判不到 -> 老对象与老组永久残留在 Base A2L 里
    pur_src = _write(os.path.join(tmp, 'pur_src.a2l'),
                     '/* Code generation for model "MDL_M" */\n'
                     + _a2l([_CM.format(name='MDL_M_CM_u'), _LAYOUT,
                             _CHAR.format(name='NEW_Sig', addr='0x0000',
                                          cm='MDL_M_CM_u', upper='9')]))
    pur_tgt = _write(os.path.join(tmp, 'pur_tgt.a2l'), _a2l([
        _CM.format(name='OLDSUB_CM_u'),
        _CM.format(name='OTH_CM_u'),
        _LAYOUT,
        _CHAR.format(name='OLD_Sig', addr='0x00001000', cm='OLDSUB_CM_u', upper='5'),
        _CHAR.format(name='OTH_Sig', addr='0x00002000', cm='OTH_CM_u', upper='5'),
        '    /begin GROUP\n      /* Name                   */      OLDSUB\n'
        '      /* Long identifier        */      "OLDSUB"\n'
        '      /begin REF_CHARACTERISTIC\n        OLD_Sig\n'
        '      /end REF_CHARACTERISTIC\n    /end GROUP\n',
        '    /begin FUNCTION\n      /* Name                   */      MDL_M\n'
        '      /* Long identifier        */      "m"\n'
        '      /begin SUB_FUNCTION\n        OLDSUB\n      /end SUB_FUNCTION\n'
        '    /end FUNCTION\n',
    ]))
    pur_map = parse_map_ownership(_write(
        os.path.join(tmp, 'pur.map'),
        _MAP_LINE.format(sym='OLD_Sig_E', obj='MDL_M')
        + _MAP_LINE.format(sym='OTH_Sig_E', obj='OTHER_MDL')))

    out_pur = os.path.join(tmp, 'pur_out.a2l')
    st_pur = sync_model_a2l(pur_src, pur_tgt, out_pur, purge=True, backup=False,
                            log=lambda m: None, owner_map=pur_map)
    pur_names = [d.split('] ')[-1] for d in st_pur['deleted_names']]
    suite.check('清理 按定义方删掉旧对象 OLD_Sig', 'OLD_Sig' in pur_names, str(pur_names))
    suite.check('清理 旧组 OLDSUB 一并删除', 'OLDSUB' in pur_names, str(pur_names))
    suite.check('清理 别的模型的对象一个都不删', 'OTH_Sig' not in pur_names, str(pur_names))
    ptxt = open(out_pur, encoding='utf-8').read()
    suite.check('清理 产物中无 OLD_Sig / OLDSUB 残留',
                'OLD_Sig' not in ptxt and 'OLDSUB' not in ptxt,
                [l for l in ptxt.splitlines() if 'OLD' in l][:3])
    suite.check('清理 别的模型对象仍在', 'OTH_Sig' in ptxt, '')

    # 不给 MAP 时只看 CM 前缀: 旧前缀对象判不到, 记录降级语义
    out_pur2 = os.path.join(tmp, 'pur_out_nomap.a2l')
    st_pur2 = sync_model_a2l(pur_src, pur_tgt, out_pur2, purge=True, backup=False,
                             log=lambda m: None)
    suite.eq('清理 无 MAP 时按旧判据一个也不删', len(st_pur2['deleted_names']), 0)
    suite.check('清理 无 MAP 时旧对象留在产物中', 'OLD_Sig' in open(
        out_pur2, encoding='utf-8').read(), '')



    blocks, _ = _parse_blocks(open(sync_out, encoding='utf-8').read().splitlines(True),
                              need_text=True)
    by_name = dict((b['name'], b) for b in blocks if b.get('name'))

    sig = by_name.get('MDL_Sig')
    suite.check('同名对象仍在', sig is not None, '')
    if sig:
        suite.check('同名对象更新为新版上限 9', 'Upper Limit            */      9'
                    in sig['text'] or '9' in sig['text'].split('Upper Limit')[-1][:20],
                    sig['text'].split('Upper Limit')[-1][:30])
        suite.check('同名对象保留整车真实地址 0x00002000',
                    '0x00002000' in sig['text'], sig['text'][:120])
        suite.check('同名对象未被写成占位地址 0x0000',
                    '0x00000000' not in sig['text'], '')

    suite.check('新增对象 MDL_New 已加入', 'MDL_New' in by_name, '')
    suite.check('旧版遗留对象 MDL_Old 已删除', 'MDL_Old' not in by_name, '')
    oth = by_name.get('OTH_Sig')
    suite.check('其他模型对象 OTH_Sig 未被改动',
                oth is not None and '0x00003000' in oth['text']
                and 'OTH_CM_u' in oth['text'],
                (oth or {}).get('text', '')[:120])

    # ---- 地址行两种写法 x 两侧交叉: 真实地址必须全部保留 ----
    # 曾只认注释式, 另一侧为 ASAP2 标准关键字式时静默把整车地址覆盖成 0x0000
    for s_label, s_tpl in (('注释', _CHAR), ('关键字', _CHAR_KW)):
        for t_label, t_tpl in (('注释', _CHAR), ('关键字', _CHAR_KW)):
            src_i = _write(os.path.join(tmp, 'as_%s.a2l' % s_label),
                           _a2l([_CM.format(name='MDL_CM_u'), _LAYOUT,
                                 s_tpl.format(name='MDL_Sig', addr='0x00000000',
                                              cm='MDL_CM_u', upper='9')]))
            tgt_i = _write(os.path.join(tmp, 'at_%s.a2l' % t_label),
                           _a2l([_CM.format(name='MDL_CM_u'), _LAYOUT,
                                 t_tpl.format(name='MDL_Sig', addr='0x00002000',
                                              cm='MDL_CM_u', upper='5')]))
            out_i = os.path.join(tmp, 'ao_%s_%s.a2l' % (s_label, t_label))
            sync_model_a2l(src_i, tgt_i, out_i, purge=False, backup=False,
                           log=lambda m: None)
            blk, _ = _parse_blocks(open(out_i, encoding='utf-8').read().splitlines(True),
                                   need_text=True)
            got = [b for b in blk if b['name'] == 'MDL_Sig']
            addr_ok = bool(got) and '0x00002000' in got[0]['text']
            suite.check('地址保留: 源%s写法 / 目标%s写法' % (s_label, t_label), addr_ok,
                        (got[0]['text'] if got else '块丢失')[:100])
