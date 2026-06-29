"""
logger.py — 统一日志模块

双通道输出：System Console (print) + Blender Info Area (report)。
所有日志自动添加时间戳前缀。
"""

import time
import bpy


# ── 日志缓冲区（供 UI 面板读取） ──
_log_buffer: list[str] = []
_MAX_BUFFER_SIZE = 50


def _get_timestamp() -> str:
    """获取当前时间戳字符串 [HH:MM:SS]"""
    return time.strftime("[%H:%M:%S]", time.localtime())


def log(msg: str, level: str = "INFO") -> None:
    """
    双通道日志输出。

    Args:
        msg: 日志消息内容
        level: 日志级别 (INFO/WARNING/ERROR)
    """
    prefix_map = {
        "INFO":    "",
        "WARNING": "WARNING: ",
        "ERROR":   "ERROR: ",
    }
    prefix = prefix_map.get(level, "")
    timestamp = _get_timestamp()
    full_msg = f"{timestamp} {prefix}{msg}"

    # 通道 1：System Console
    print(full_msg)

    # 通道 2：Blender Info Area
    try:
        w = bpy.context.window
        if w:
            report_type = level if level in ("INFO", "WARNING", "ERROR") else "INFO"
            with bpy.context.temp_override(window=w):
                bpy.ops.wm.report(type=report_type, message=str(msg))
    except Exception:
        pass  # report 不可用时静默跳过

    # 缓冲区记录
    _log_buffer.append(full_msg)
    if len(_log_buffer) > _MAX_BUFFER_SIZE:
        _log_buffer.pop(0)


def info(msg: str) -> None:
    """输出 INFO 级别日志。"""
    log(msg, "INFO")


def warn(msg: str) -> None:
    """输出 WARNING 级别日志。"""
    log(msg, "WARNING")


def error(msg: str) -> None:
    """输出 ERROR 级别日志。"""
    log(msg, "ERROR")


def summary(stats: dict) -> None:
    """
    格式化输出操作统计摘要。

    Args:
        stats: 包含各统计字段的字典
    """
    lines = ["=" * 50, "  操作统计摘要", "=" * 50]
    for key, value in stats.items():
        lines.append(f"  {key}: {value}")
    lines.append("=" * 50)
    for line in lines:
        log(line, "INFO")


def get_log_lines(count: int = 20) -> list[str]:
    """获取最近的 N 条日志行 (供 UI 面板使用)。"""
    return _log_buffer[-count:]


def clear_log() -> None:
    """清空日志缓冲区。"""
    _log_buffer.clear()
    log("日志已清空", "INFO")
