#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""日志工具模块 - 提供日志着色和保存功能"""

from datetime import datetime
from pathlib import Path


def pick_log_tag(msg):
    """根据内容自动选择日志颜色标签"""
    s = msg.strip()
    if s.startswith("错误") or "失败" in s or s.startswith("Traceback") or s.startswith(" ") and "错误" in s:
        return "err"
    if "[警告]" in s or s.startswith("[保持]") or "警告" in s:
        return "warn"
    if s.startswith(">>>") or "完成" in s or "已保存" in s or "已备份" in s:
        return "ok"
    if s in ("统计汇总", "合并统计", "同步统计", "=== 测试解析 ==="):
        return "title"
    if set(s) <= {'=', '-'} and s:
        return "dim"
    return None


def timestamp(fmt="display"):
    """生成时间戳"""
    if fmt == "file":
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_log_file(log_buffer, log_queue, output_path):
    """保存日志到文件
    
    Args:
        log_buffer: 已渲染的日志列表
        log_queue: 待渲染的日志队列
        output_path: 输出文件路径
    
    Returns:
        日志文件路径，失败返回 None
    """
    lines = log_buffer + log_queue
    if not lines:
        return None
    try:
        p = Path(output_path)
        ts = timestamp("file")
        log_path = p.parent / f"{p.stem}_{ts}.log"
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("A2L 工具箱 处理日志\n")
            f.write(f"时间: {timestamp()}\n")
            f.write("=" * 80 + "\n\n")
            for line in lines:
                f.write(line + "\n")
        return str(log_path)
    except Exception:
        return None