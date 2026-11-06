#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动加载屏 - 主窗口就绪前的过渡动画.

纯 tkinter Canvas 实现, 不依赖图片资源, 因此打包时无需额外文件; 视觉沿用主题色板.

用法 (main.py):
    root = tk.Tk(); root.withdraw()
    splash = SplashScreen(root); splash.show()
    ... 后台导入 / 构建主窗口 ...
    splash.step('构建主窗口…', 90)
    splash.close(on_done=lambda: root.deiconify())
"""

import sys
import time
import traceback
import tkinter as tk

from gui.theme import COLORS, FONT_FAMILY
from utils.config import VERSION

_CARD = COLORS['card']
_EDGE = COLORS['border']
_FG_TITLE = COLORS['text']
_FG_DIM = '#6b7280'
_TRACK = '#e5eaf2'
_ACCENT = COLORS['primary']

_MIN_SHOW_MS = 450          # 最短展示时长: 机器快时也留够一帧动画, 避免一闪而过
_FRAME_MS = 33              # 约 30fps
_FADE_OUT_MS = 180          # 淡出总时长
_FADE_STEPS = 6


def blend(color_a, color_b, t):
    """color_a 按比例 t 混向 color_b (t=0 保持 color_a, t=1 变成 color_b)"""
    t = max(0.0, min(1.0, t))
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


class SplashScreen:
    """无边框加载窗: 12 段弧旋转 + 步骤文字 + 细进度条."""

    SEGMENTS = 12

    def __init__(self, parent, width=420, height=214):
        self.parent = parent
        self.win = None
        self._closed = False
        self._angle = 0
        self._job = None
        self.t_shown = None
        self.t_first_frame = None

        # 高分屏按 DPI 比例放大 (main 里已 SetProcessDpiAwareness(1))
        try:
            self.scale = max(1.0, min(2.0, parent.winfo_fpixels('1i') / 96.0))
        except tk.TclError:
            self.scale = 1.0
        s = self.scale
        w, h = int(width * s), int(height * s)

        win = tk.Toplevel(parent)
        win.withdraw()
        win.overrideredirect(True)
        for attr, val in (('-topmost', True), ('-alpha', 0.99)):
            try:
                win.attributes(attr, val)
            except tk.TclError:
                pass
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry('%dx%d+%d+%d' % (w, h, (sw - w) // 2, (sh - h) // 2))
        win.configure(bg=_EDGE)
        self.win = win

        card = tk.Frame(win, bg=_CARD)
        card.pack(fill='both', expand=True, padx=max(1, int(s)), pady=max(1, int(s)))

        tk.Label(card, text='A2L 工具箱', bg=_CARD, fg=_FG_TITLE,
                 font=(FONT_FAMILY, int(16 * s), 'bold')).pack(pady=(int(26 * s), 0))
        tk.Label(card, text=VERSION, bg=_CARD, fg=_FG_DIM,
                 font=(FONT_FAMILY, int(9 * s))).pack(pady=(int(2 * s), 0))

        spin = int(46 * s)
        self.canvas = tk.Canvas(card, width=spin, height=spin, bg=_CARD,
                                highlightthickness=0, bd=0)
        self.canvas.pack(pady=(int(14 * s), 0))
        self._spin_box = (int(5 * s), int(5 * s), spin - int(5 * s), spin - int(5 * s))
        self._arc_width = max(2, int(3 * s))

        self.text_var = tk.StringVar(value='正在启动…')
        tk.Label(card, textvariable=self.text_var, bg=_CARD, fg=_FG_DIM,
                 font=(FONT_FAMILY, int(9 * s))).pack(pady=(int(10 * s), 0))

        bar_w = int(220 * s)
        self.progress = tk.Canvas(card, width=bar_w, height=max(2, int(3 * s)),
                                  bg=_CARD, highlightthickness=0, bd=0)
        self.progress.pack(pady=(int(9 * s), 0))
        self._bar_w = bar_w
        self._bar_h = max(2, int(3 * s))
        self._track = self.progress.create_rectangle(
            0, 0, bar_w, self._bar_h, fill=_TRACK, outline='')
        self._fill = self.progress.create_rectangle(
            0, 0, 0, self._bar_h, fill=_ACCENT, outline='')
        self._pct = 0

    # ---------- 对外接口 ----------
    def show(self):
        """显示加载屏并开始动画 (非阻塞)"""
        if self.win is None or self._closed:
            return
        self.t_shown = time.perf_counter()
        self.win.deiconify()
        self.win.update_idletasks()
        self.t_first_frame = time.perf_counter()
        self._tick()

    def step(self, text, pct):
        """更新阶段文字与进度 (pct: 0-100)"""
        if self._closed or self.win is None:
            return
        try:
            self.text_var.set(text)
            self._pct = max(0, min(100, int(pct)))
            self.progress.coords(self._fill, 0, 0,
                                 int(self._bar_w * self._pct / 100.0), self._bar_h)
            self.win.update_idletasks()
        except tk.TclError:
            pass

    def close(self, on_done=None):
        """淡出并销毁; 保证至少展示 _MIN_SHOW_MS 毫秒.

        on_done 在窗口销毁后调用 (主线程), 用于显示主窗口.
        """
        if self._closed:
            if on_done:
                on_done()
            return
        self._closed = True
        elapsed_ms = 0.0
        if self.t_shown is not None:
            elapsed_ms = (time.perf_counter() - self.t_shown) * 1000.0
        delay = max(0, int(_MIN_SHOW_MS - elapsed_ms))
        try:
            self.parent.after(delay, lambda: self._fade_out(on_done, _FADE_STEPS))
        except tk.TclError:
            self._destroy()
            if on_done:
                on_done()

    def abort(self):
        """立即销毁 (异常路径: 不允许留下一个永远转圈的窗口)"""
        self._closed = True
        self._destroy()

    # ---------- 内部 ----------
    def _tick(self):
        if self._closed or self.win is None:
            return
        try:
            self.canvas.delete('seg')
            x0, y0, x1, y1 = self._spin_box
            for i in range(self.SEGMENTS):
                # 尾段向白底渐隐, 形成拖尾
                t = (i / float(self.SEGMENTS - 1)) ** 1.4 * 0.82
                self.canvas.create_arc(
                    x0, y0, x1, y1, style='arc', outline=blend(_ACCENT, _CARD, t),
                    width=self._arc_width, start=-self._angle + i * (360.0 / self.SEGMENTS),
                    extent=360.0 / self.SEGMENTS - 8, tags='seg')
            self._angle = (self._angle + 12) % 360
            self._job = self.win.after(_FRAME_MS, self._tick)
        except tk.TclError:
            pass

    def _fade_out(self, on_done, steps_left):
        if self.win is None:
            if on_done:
                on_done()
            return
        try:
            if steps_left <= 0:
                self._destroy()
                if on_done:
                    self._run(on_done)
                return
            alpha = max(0.0, 1.0 - (1.0 - steps_left / float(_FADE_STEPS)))
            self.win.attributes('-alpha', alpha)
            self.parent.after(_FADE_OUT_MS // _FADE_STEPS,
                              lambda: self._fade_out(on_done, steps_left - 1))
        except tk.TclError:
            self._destroy()
            if on_done:
                self._run(on_done)

    def _destroy(self):
        if self._job is not None and self.win is not None:
            try:
                self.win.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None

    @staticmethod
    def _run(fn):
        try:
            fn()
        except Exception:
            traceback.print_exc(file=sys.stderr)


def _demo():  # pragma: no cover - 手动预览: python -m gui.splash
    root = tk.Tk()
    root.withdraw()
    sp = SplashScreen(root)
    sp.show()
    stages = [('正在初始化界面…', 35), ('正在加载图表组件…', 70), ('构建主窗口…', 90)]
    for i, (text, pct) in enumerate(stages):
        root.after(600 * (i + 1), lambda t=text, p=pct: sp.step(t, p))
    root.after(2400, lambda: sp.close(on_done=root.destroy))
    root.mainloop()


if __name__ == '__main__':  # pragma: no cover
    _demo()
