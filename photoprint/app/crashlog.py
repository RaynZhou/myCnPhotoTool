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


def log_path() -> Path:
    """与配置同目录（%APPDATA%\\PhotoPrint\\error.log）。"""
    return store.default_path().parent / LOG_NAME


def write(exc_info, path=None):
    """把 traceback 追加写入日志，返回日志路径；写失败返回 None。"""
    target = Path(path) if path else log_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write("".join(traceback.format_exception(*exc_info)) + "\n")
    except OSError:
        return None
    return target


def install(path=None) -> Path:
    """装主线程与子线程两个钩子。Qt 槽内的异常走 sys.excepthook。"""
    target = Path(path) if path else None

    def hook(etype, value, tb):
        write((etype, value, tb), target)

    def thread_hook(args):
        write((args.exc_type, args.exc_value, args.exc_traceback), target)

    sys.excepthook = hook
    threading.excepthook = thread_hook
    return target or log_path()
