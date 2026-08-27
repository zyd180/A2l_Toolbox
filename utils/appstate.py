#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""应用状态持久化 - 最近使用的文件路径等 (存于用户主目录)"""

import json
from pathlib import Path

_CFG = Path.home() / '.a2l_toolbox_session.json'


def load_app_state():
    """读取应用状态, 失败返回空 dict"""
    try:
        with open(_CFG, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_app_state(**kwargs):
    """合并保存应用状态字段"""
    state = load_app_state()
    state.update(kwargs)
    try:
        with open(_CFG, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
