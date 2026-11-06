#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""回归入口: python test/regress/run_all.py

无第三方测试框架依赖 (CI 只装 requirements.txt 里的 matplotlib).
退出码: 0 全通过, 1 有失败.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _harness  # noqa: E402

MODULES = [
    'test_hex_format',
    'test_calib_engine',
    'test_a2l_tools',
    'test_gui_widgets',
    'test_gui_contract',
]


def main():
    suites = []
    for name in MODULES:
        try:
            mod = __import__(name)
        except Exception as e:
            import traceback
            traceback.print_exc()
            s = _harness.Suite(name)
            s.check('模块可导入', False, repr(e))
            suites.append(s)
            continue
        print('>>> %s' % name)
        suites.append(_harness.run_module(mod))
    return _harness.report(suites)


if __name__ == '__main__':
    sys.exit(main())
