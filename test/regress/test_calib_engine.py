#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在线标定引擎回归 (calib_engine.CalibSession).

覆盖最易错的机制: COEFFS 方向 (Simulink phys->raw)、限值、COM_AXIS/FIX_AXIS 轴值、
MAP 的 COLUMN_DIR 存储方向、脏标记/撤销、MEMORY_SEGMENT 补 0xFF、DCM 往返.
"""

import os

import _harness  # noqa: F401
import fixtures
from core.calib_engine import CalibSession
from core.hex_handler import load_intel_hex


def _load(suite, hex_name=None):
    tmp = suite.tmpdir()
    a2l, hx = fixtures.write_fixture(tmp)
    return CalibSession.load(a2l, hx, log=lambda m: None), a2l, hx, tmp


def run(suite):
    tmp = suite.tmpdir()
    a2l, hx = fixtures.write_fixture(tmp)
    s = CalibSession.load(a2l, hx, log=lambda m: None)

    suite.eq('解析出 5 个标定量', len(s.objects), 5)
    suite.eq('解析出 3 个轴点对象', len(s.axis_pts), 3)
    suite.eq('解析出 2 个转换方法', len(s.cms), 2)
    suite.eq('解析出 1 个 MEMORY_SEGMENT',
             s.mem_segments, [(fixtures.SEG_START, fixtures.SEG_START + fixtures.SEG_SIZE)])

    # ---- 1) COEFFS 方向: raw 50 经 x10 应为 5.0 (若方向反了会得 500) ----
    suite.close('COEFFS 按 phys->raw 解码 (raw50/x10=5.0)',
                s.read_object(s.objects['Sca_Val']), [5.0])

    # ---- 2) 全部对象值 ----
    for name, expect in fixtures.EXPECTED.items():
        obj = s.objects.get(name) or s.axis_pts.get(name)
        suite.close('对象值 %s' % name, s.read_object(obj), expect)

    # ---- 3) MAP 存储方向 COLUMN_DIR: k = c*ny + r ----
    m = s.objects['Map_2D']
    suite.eq('MAP shape', m.shape, (3, 2))
    expect_k = {(0, 0): 0, (1, 0): 1, (0, 1): 2, (1, 1): 3, (0, 2): 4, (1, 2): 5}
    for (r, c), k in expect_k.items():
        suite.eq('grid_to_flat(%d,%d)=%d' % (r, c, k), s.grid_to_flat(m, r, c), k)
    suite.eq('flat_to_grid(5)', s.flat_to_grid(m, 5), (1, 2))

    # 按网格写入 (r=1,c=2) 应落在第 6 个字 (addr+10)
    errs = s.write_values(m, [99.0], [s.grid_to_flat(m, 1, 2)])
    suite.check('按网格写入无错误', not errs, str(errs))
    suite.eq('网格(r1,c2) 写入落在 addr+10', s.mem.get(m.addr + 10), 99 & 0xFF)
    suite.eq('网格写入后 read_object[5]', s.read_object(m)[5], 99.0)
    suite.eq('网格写入不影响 [4]', s.read_object(m)[4], 31.0)
    s.restore_object(m)

    # ---- 4) 编码方向: 写 7.5 -> raw 75 ----
    sca = s.objects['Sca_Val']
    errs = s.write_values(sca, [7.5], [0])
    suite.check('写入 7.5 无错误', not errs, str(errs))
    suite.eq('raw = 75 小端低字节', (s.mem.get(sca.addr), s.mem.get(sca.addr + 1)), (75, 0))
    suite.eq('读回 7.5', s.read_object(sca)[0], 7.5)

    # ---- 5) 限值保护 ----
    before = dict(s.mem)
    errs = s.write_values(sca, [200.0], [0])
    suite.check('超上限写入被拒绝', bool(errs), 'errs=%r' % (errs,))
    suite.eq('被拒绝时内存未变', dict(s.mem), before)

    # ---- 6) 脏标记 / 撤销 / 重做 / 还原 (必须在其他写入之前, 保证栈顶是本条命令) ----
    suite.eq('写入后脏格集合', s.dirty_cells(sca), {0})
    suite.check('undo 生效', s.undo() and s.read_object(sca)[0] == 5.0,
                str(s.read_object(sca)))
    suite.check('redo 生效', s.redo() and s.read_object(sca)[0] == 7.5,
                str(s.read_object(sca)))
    suite.check('restore_object 生效', s.restore_object(sca) and
                s.read_object(sca)[0] == 5.0 and not s.dirty_cells(sca),
                str(s.read_object(sca)))

    # ---- 7) 轴: COM_AXIS 读 + 联动写 ----
    suite.close('COM_AXIS 轴值来自 HEX', s.read_axis(s.objects['Cur_Curve'], 0),
                fixtures.EXPECTED['AX_Cur'])
    ax = s.axis_pts['AX_Cur']
    errs = s.write_values(ax, [555.0], [2])       # 轴上限 655.34, 必须在限值内
    suite.check('轴点写入无错误', not errs, str(errs))
    suite.close('轴点写入后曲线 X 轴联动', s.read_axis(s.objects['Cur_Curve'], 0),
                [0.0, 100.0, 555.0, 300.0, 400.0])
    s.restore_object(ax)

    # ---- 8) FIX_AXIS: 隐式轴, 不占存储, 值来自 FIX_AXIS_PAR_DIST ----
    suite.close('FIX_AXIS 轴值', s.read_axis(s.objects['Fix_Curve'], 0),
                fixtures.EXPECTED_FIX_AXIS)
    suite.eq('FIX_AXIS 轴不占 HEX 存储 (对象数据仍连续)',
             s.objects['Fix_Curve'].addr, 0x1034)

    # ---- 9) 保存: 段内补 0xFF, 段外不铺 ----
    out = os.path.join(tmp, 'saved.hex')
    s.save_hex(out)
    saved = load_intel_hex(out)
    fill_start, fill_end = fixtures.FILL_RANGE
    holes = [a for a in range(fill_start, fill_end) if saved.get(a) != 0xFF]
    suite.check('段内缺字节补 0xFF', not holes,
                '未填充 %d 个, 首=%s' % (len(holes), hex(holes[0]) if holes else None))
    suite.check('段外地址不被铺开', 0x2000 not in saved, '')
    suite.eq('填充不影响既有数据', saved.get(0x1000), 50)

    # ---- 10) 写入 -> 保存 -> 重载 值保持 ----
    s.write_values(sca, [7.5], [0])
    out2 = os.path.join(tmp, 'saved2.hex')
    s.save_hex(out2)
    s2 = CalibSession.load(a2l, out2, log=lambda m: None)
    suite.eq('重载后写入值保持', s2.read_object(s2.objects['Sca_Val'])[0], 7.5)
    suite.eq('重载后脏标记为空', s2.dirty_cells(s2.objects['Sca_Val']), set())

    # ---- 11) DCM 往返: 导出 -> 应用到全零基线 -> 值一致 ----
    ref = CalibSession.load(a2l, hx, log=lambda m: None)
    dcm_path = os.path.join(tmp, 'out.dcm')
    st = ref.export_dcm(dcm_path, only_dirty=False, log=lambda m: None)
    suite.check('导出 DCM 覆盖全部可读对象', st['exported'] >= 8 and not st['skipped'],
                'exported=%d skipped=%d' % (st['exported'], st['skipped']))

    zero_a2l, zero_hex = fixtures.write_fixture(os.path.join(tmp, 'zero'), zeroed=True)
    z = CalibSession.load(zero_a2l, zero_hex, log=lambda m: None)
    suite.close('全零基线读到的值确实为 0',
                [z.read_object(z.objects['Sca_Val'])[0],
                 z.read_object(z.objects['Map_2D'])[5]], [0.0, 0.0])
    res = z.apply_dcm(dcm_path, log=lambda m: None)
    suite.check('导入 DCM 无错误', res['applied'] >= 8 and not res['errors'] and
                res['missing'] == 0,
                'applied=%d missing=%d errors=%r'
                % (res['applied'], res['missing'], res['errors'][:2]))
    bad = []
    for name, expect in fixtures.EXPECTED.items():
        obj = z.objects.get(name) or z.axis_pts.get(name)
        got = z.read_object(obj)
        if len(got) != len(expect) or any(
                g is None or abs(g - e) > 1e-6 for g, e in zip(got, expect)):
            bad.append((name, got, expect))
    suite.check('DCM 写入后全部对象值还原正确', not bad, str(bad[:2]))
    suite.check('导入产生了实际改动 (脏对象数 > 0)', len(z.dirty_objects()) > 0,
                'dirty=%d' % len(z.dirty_objects()))
