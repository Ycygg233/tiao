"""_thinking.py — 请求进行中动画（纯函数，无线程）

单线程同步绘制，由 _stream.py 在流式读取空闲期调用。
使用 Braille 空心点阵 spinner，语义中性，帧率波动不易感知。
"""

import sys

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def draw_frame(frame: int) -> None:
    """绘制一帧 spinner（主线程同步调用，无锁安全）。

    frame 递增即可，内部自动循环取模。
    """
    sys.stdout.write(f"\r\033[K{_SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]}")
    sys.stdout.flush()


def clear_line() -> None:
    """清除当前行，将光标留在行首。

    在 console.print() 输出内容前调用，防止动画字符残留。
    使用 ANSI EL (Erase in Line) 序列，不依赖终端列数。
    """
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()
