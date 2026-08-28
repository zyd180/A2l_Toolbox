#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""页签注册表.

A2L_TABS  : "A2L处理" 大导航下的三个子页签 (顺序即展示顺序)
CALIB_TAB : "在线标定" 大导航页签
"""

from gui.tabs.addr import AddrTab
from gui.tabs.merge import MergeTab
from gui.tabs.sync import SyncTab
from gui.tabs.calib.tab import CalibTab

A2L_TABS = [AddrTab, MergeTab, SyncTab]
CALIB_TAB = CalibTab
