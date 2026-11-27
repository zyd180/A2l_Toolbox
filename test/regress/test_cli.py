#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""命令行模式回归: cli.run() 进程内直调, 覆盖四个子命令与退出码.

exe 壳 (main.py 带参分发 / AttachConsole) 不在本用例范围, 打包后手工验证.
"""

import os

import _harness  # noqa: F401
import fixtures
import cli
from core.a2l_parser import extract_a2l_variables, get_a2l_blocks
from core.calib_engine import CalibSession
from test_a2l_tools import (_a2l, _CM, _LAYOUT, _CHAR, _MODEL_A2L,
                            _MAP_LINE, _write)


def _map_line(sym, addr, obj='MDL_A'):
    return '0x%08X 0x%08X  1 g %s  PF1_Cal  .rodata  ASW\\code\\%s.o\n' % (
        addr, addr, sym, obj)


def run(suite):
    tmp = suite.tmpdir()

    # ==================== addr ====================
    a2l, _hex = fixtures.write_fixture(os.path.join(tmp, 'addr'))
    mp = _write(os.path.join(tmp, 'addr.map'), _map_line('Sca_Val', 0x3000))
    out = os.path.join(tmp, 'addr_out.a2l')
    suite.eq('addr 退出码 0', cli.run(['addr', '--src', mp, '--in', a2l,
                                      '--out', out]), 0)
    suite.check('addr 地址已更新', '0x00003000' in
                open(out, encoding='utf-8').read(), '')

    partial = _write(os.path.join(tmp, 'partial.a2l'), _a2l([
        _CM.format(name='MDL_CM_u'), _LAYOUT,
        _CHAR.format(name='A_Has', addr='0x80401234', cm='MDL_CM_u', upper='9'),
        _CHAR.format(name='B_Empty', addr='0x00000000', cm='MDL_CM_u', upper='9'),
    ]))
    mp2 = _write(os.path.join(tmp, 'partial.map'),
                 _map_line('A_Has', 0x3000) + _map_line('B_Empty', 0x4000))
    out_keep = os.path.join(tmp, 'keep.a2l')
    suite.eq('addr --only-missing 退出码 0',
             cli.run(['addr', '--src', mp2, '--in', partial,
                      '--out', out_keep, '--only-missing']), 0)
    ktxt = open(out_keep, encoding='utf-8').read()
    suite.check('addr --only-missing 保留已有地址',
                '0x80401234' in ktxt and '0x00004000' in ktxt, '')
    out_all = os.path.join(tmp, 'all.a2l')
    cli.run(['addr', '--src', mp2, '--in', partial, '--out', out_all])
    atxt = open(out_all, encoding='utf-8').read()
    suite.check('addr 默认覆盖已有地址',
                '0x00003000' in atxt and '0x80401234' not in atxt, '')

    suite.eq('addr 输入不存在退出码 1',
             cli.run(['addr', '--src', mp, '--in', os.path.join(tmp, 'no.a2l'),
                      '--out', out]), 1)
    suite.eq('addr 缺参数退出码 2', cli.run(['addr', '--src', mp]), 2)
    suite.eq('--version 退出码 0', cli.run(['--version']), 0)

    # ==================== merge ====================
    d = os.path.join(tmp, 'merge_dir')
    os.makedirs(d, exist_ok=True)
    _write(os.path.join(d, 'MDL_A.a2l'),
           _MODEL_A2L.format(model='MDL_A', cm='MDL_A_CM_u', name='Dup_Sig',
                             longid='from A', upper='3.0'))
    _write(os.path.join(d, 'MDL_B.a2l'),
           _MODEL_A2L.format(model='MDL_B', cm='MDL_B_CM_u', name='Dup_Sig',
                             longid='from B', upper='255.0'))
    mp3 = _write(os.path.join(tmp, 'owner.map'),
                 _MAP_LINE.format(sym='Dup_Sig_MP', obj='MDL_A'))
    mout = os.path.join(tmp, 'merged.a2l')
    suite.eq('merge 退出码 0',
             cli.run(['merge', '--folder', d, '--out', mout, '--map', mp3]), 0)
    suite.eq('merge 同名去重只剩 1 块',
             len([b for b in get_a2l_blocks(mout)
                  if b.get('name') == 'Dup_Sig']), 1)
    suite.eq('merge --upd-addr 无 MAP 退出码 2',
             cli.run(['merge', '--folder', d, '--out', mout, '--upd-addr']), 2)
    mout2 = os.path.join(tmp, 'merged_addr.a2l')
    suite.eq('merge --upd-addr 退出码 0',
             cli.run(['merge', '--folder', d, '--out', mout2,
                      '--map', mp3, '--upd-addr']), 0)

    # ==================== sync ====================
    src = _write(os.path.join(tmp, 'src.a2l'), _a2l([
        _CM.format(name='MDL_CM_u'), _LAYOUT,
        _CHAR.format(name='MDL_Sig', addr='0x0000', cm='MDL_CM_u', upper='9'),
        _CHAR.format(name='MDL_New', addr='0x0000', cm='MDL_CM_u', upper='7'),
    ]))
    base = _write(os.path.join(tmp, 'base.a2l'), _a2l([
        _CM.format(name='MDL_CM_u'), _LAYOUT,
        _CHAR.format(name='MDL_Sig', addr='0x00002000', cm='MDL_CM_u', upper='5'),
    ]))
    sout = os.path.join(tmp, 'sync_out.a2l')
    suite.eq('sync 退出码 0',
             cli.run(['sync', '--src', src, '--base', base, '--out', sout]), 0)
    stxt = open(sout, encoding='utf-8').read()
    suite.check('sync 保留整车真实地址', '0x00002000' in stxt, '')
    suite.check('sync 新对象已插入', 'MDL_New' in stxt, '')
    mp4 = _write(os.path.join(tmp, 'sync.map'), _map_line('MDL_New', 0x5000))
    suite.eq('sync --addr --only-missing 退出码 0',
             cli.run(['sync', '--src', src, '--base', base, '--out', sout,
                      '--addr', mp4, '--only-missing']), 0)
    stxt2 = open(sout, encoding='utf-8').read()
    suite.check('sync 后地址步骤填补占位', '0x00005000' in stxt2, '')
    suite.check('sync 后地址步骤不动已有地址', '0x00002000' in stxt2, '')

    # ==================== dcm ====================
    dcm_dir = os.path.join(tmp, 'dcm')
    ra2l, rhex = fixtures.write_fixture(dcm_dir)
    ref = CalibSession.load(ra2l, rhex, log=lambda m: None)
    dcm = os.path.join(dcm_dir, 'ref.dcm')
    ref.export_dcm(dcm, only_dirty=False, log=lambda m: None)
    zdir = os.path.join(tmp, 'dcm_zero')
    za2l, zhex = fixtures.write_fixture(zdir, zeroed=True)
    dout = os.path.join(tmp, 'dcm_out.hex')
    suite.eq('dcm 退出码 0',
             cli.run(['dcm', '--dcm', dcm, '--a2l', za2l,
                      '--hex', zhex, '--out', dout]), 0)
    suite.check('dcm 输出文件存在', os.path.exists(dout), '')
    z = CalibSession.load(za2l, dout, log=lambda m: None)
    bad = []
    for name, expect in fixtures.EXPECTED.items():
        obj = z.objects.get(name) or z.axis_pts.get(name)
        got = z.read_object(obj)
        if len(got) != len(expect) or any(
                g is None or abs(g - e) > 1e-6 for g, e in zip(got, expect)):
            bad.append(name)
    suite.check('dcm 写入后全部对象值与参考一致', not bad, str(bad[:3]))