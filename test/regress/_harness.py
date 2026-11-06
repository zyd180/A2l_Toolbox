#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""极简断言框架 (CI 只装了 matplotlib, 不引入 pytest 依赖).

用法: suite = Suite('x'); suite.eq('名称', 实际, 期望); run_all 汇总.
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class Suite(object):

    def __init__(self, title):
        self.title = title
        self.items = []
        self._tmp = None

    # ---------- 断言 ----------
    def check(self, name, ok, detail=''):
        self.items.append((name, bool(ok), detail))
        return bool(ok)

    def eq(self, name, actual, expected):
        ok = actual == expected
        return self.check(name, ok,
                          '' if ok else '实际=%r 期望=%r' % (actual, expected))

    def close(self, name, actual, expected, tol=1e-6):
        try:
            ok = (actual is not None and len(actual) == len(expected) and
                  all(abs(float(a) - float(e)) <= tol for a, e in zip(actual, expected)))
        except (TypeError, ValueError):
            ok = False
        return self.check(name, ok,
                          '' if ok else '实际=%r 期望=%r' % (actual, expected))

    # ---------- 临时目录 ----------
    def tmpdir(self):
        if self._tmp is None:
            self._tmp = tempfile.mkdtemp(prefix='a2l_regress_')
        return self._tmp

    def cleanup(self):
        if self._tmp and os.path.isdir(self._tmp):
            import shutil
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None


def run_module(module):
    suite = Suite(module.__name__)
    try:
        module.run(suite)
    except Exception as e:
        import traceback
        traceback.print_exc()
        suite.check('%s 执行未抛异常' % module.__name__, False, str(e))
    finally:
        suite.cleanup()
    return suite


def report(suites):
    total = passed = 0
    failed = []
    for s in suites:
        print('\n--- %s ---' % s.title)
        for name, ok, detail in s.items:
            total += 1
            if ok:
                passed += 1
                print('  PASS  %s' % name)
            else:
                print('  FAIL  %s   %s' % (name, detail))
                failed.append('%s::%s' % (s.title, name))
    print('\n' + '=' * 64)
    print('%d/%d 通过' % (passed, total))
    if failed:
        print('失败 %d 项:' % len(failed))
        for f in failed:
            print('  - ' + f)
    return 1 if failed else 0
