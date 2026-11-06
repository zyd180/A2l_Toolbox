#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""单模块回归 (变异测试用: 改坏一处后只看对应模块)"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import _harness  # noqa: E402

if __name__ == '__main__':
    name = sys.argv[1]
    mod = __import__(name)
    sys.exit(_harness.report([_harness.run_module(mod)]))
