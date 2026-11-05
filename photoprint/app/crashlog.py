"""崩溃日志：窗口化 exe 没有控制台，异常只能落盘才看得见。

日志写失败绝不反过来抛：诊断手段不得拖垮主流程。
"""
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

from photoprint.core import store

LOG_NAME = "error.log"
_UI_CALLBACK = None    # 崩溃落日志后给界面的回调（仅主线程钩子调）


def set_ui_callback(cb) -> None:
    """注册崩溃后的界面回调（收一个日志 Path）；传 None 可撤销。

    启动早期（窗口未建）先 `install()` 保护启动崩溃、此时回调为空；
    建好 `MainWindow` 后由入口再调本函数接上状态栏提示。
    """
    global _UI_CALLBACK
    _UI_CALLBACK = cb


def log_path() -> Path:
    """与配置同目录（%APPDATA%\\PhotoPrint\\error.log）。"""
    return store.default_path().parent / LOG_NAME


def write(exc_info, path=None):
    """把 traceback 追加写入日志，返回日志路径；写失败返回 None。

    异常一律收敛、无逃逸路径：路径构造、建目录、格式化、编码全部纳入 try。
    兜底 except Exception 而非只 OSError——本模块的契约是“诊断不得拖垮主流程”，
    畸形 exc_info（TypeError/ValueError）与孤立代理项编码错（UnicodeEncodeError）
    都得收敛成 None。不捕 BaseException：放行 KeyboardInterrupt/SystemExit。
    """
    try:
        target = Path(path) if path else log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write("".join(traceback.format_exception(*exc_info)) + "\n")
    except Exception:
        return None
    return target


def install(path=None) -> Path:
    """装主线程与子线程两个钩子。Qt 槽内的异常走 sys.excepthook。"""
    target = Path(path) if path else None

    def hook(etype, value, tb):
        written = write((etype, value, tb), target)
        # 主线程才能碰界面；提示本身坏了也不能反过来掩盖原异常处理。
        if written is not None and _UI_CALLBACK is not None:
            try:
                _UI_CALLBACK(written)
            except Exception:
                pass

    def thread_hook(args):
        # 子线程钩子只落盘、不回调 UI：跨线程改 QWidget 不安全。
        write((args.exc_type, args.exc_value, args.exc_traceback), target)

    sys.excepthook = hook
    threading.excepthook = thread_hook
    return target or log_path()
