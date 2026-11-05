"""窗口化 exe 没有控制台，异常只能落盘才看得见。"""
import sys
import threading
import types

import pytest

from photoprint.app import crashlog


def test_log_path_sits_next_to_config(tmp_path, monkeypatch):
    monkeypatch.setattr(crashlog.store, "default_path",
                        lambda: tmp_path / "PhotoPrint" / "papers.json")
    assert crashlog.log_path() == tmp_path / "PhotoPrint" / "error.log"


def test_write_appends_traceback(tmp_path):
    p = tmp_path / "error.log"
    try:
        raise ValueError("A4 放不下 5R")
    except ValueError:
        got = crashlog.write(sys.exc_info(), p)
    assert got == p
    text = p.read_text(encoding="utf-8")
    assert "ValueError" in text and "A4 放不下 5R" in text


def test_write_creates_missing_parent_dir(tmp_path):
    """日志目录还没建时 write 要用 mkdir(parents=True) 补上（真实首次运行
    即此情形）：不建则 open 抛 FileNotFoundError 被吞掉、返回 None，首启崩溃反而
    留不下任何日志。tmp_path 下两级子目录都预先不存在。"""
    p = tmp_path / "PhotoPrint" / "nested" / "error.log"
    try:
        raise ValueError("首启")
    except ValueError:
        got = crashlog.write(sys.exc_info(), p)
    assert got == p and p.exists()


def test_write_appends_instead_of_overwriting(tmp_path):
    p = tmp_path / "error.log"
    for _ in range(2):
        try:
            raise KeyError("sheet_key")
        except KeyError:
            crashlog.write(sys.exc_info(), p)
    # 钉的是“追加两条、没互相覆盖”，而非某易变字符串出现几次：一次 traceback 里
    # KeyError 会出现两遍（源码行 raise KeyError(...) + 末尾 KeyError: 'sheet_key'），
    # 按计划原写法 count("KeyError")==2 恒不成立。改数“Traceback 抬头”条数，直读意图且
    # 不受 traceback 具体排版影响。
    text = p.read_text(encoding="utf-8")
    assert text.count("Traceback (most recent call last)") == 2
    assert text.count("KeyError: 'sheet_key'") == 2


def test_write_failure_returns_none(tmp_path):
    """日志路径是个目录时不得抛：日志不能反过来拖垮进程。"""
    assert crashlog.write((ValueError, ValueError("x"), None), tmp_path) is None


@pytest.mark.parametrize("bad_exc_info,bad_path", [
    ("oops", None),                        # 解包不成三元组 → TypeError
    ((ValueError,), None),                 # value 缺 → TypeError
    ((ValueError, "x"), None),             # tb 缺 → ValueError
    ((str, "not-exc", None), None),        # 非异常类 → AttributeError
    ((ValueError, ValueError("x"), None), 5),   # path=5 → Path(5) TypeError（原在 try 外）
])
def test_write_never_raises_on_malformed_input(bad_exc_info, bad_path):
    """“异常一律收敛”契约：任何畸形入参都只能返 None，不得穿出（窗口化 exe
    无控制台，外抛即静默闪退）。只捕 OSError 的写法会让前四条仍外抛。畸形
    exc_info 在 format_exception 阶段就报错、path=5 在 Path() 就报错，都进不了
    真正写盘那步，故不会污染真 %APPDATA%。"""
    assert crashlog.write(bad_exc_info, bad_path) is None


def test_install_replaces_both_hooks(tmp_path):
    old, old_thread = sys.excepthook, threading.excepthook
    target = tmp_path / "error.log"
    try:
        crashlog.install(target)
        try:
            raise RuntimeError("预览炸了")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        assert "RuntimeError" in target.read_text(encoding="utf-8")
        # 名字叫 both_hooks 就得两条钩子都真承重：threading.excepthook 收的是
        # 一个带 exc_type/exc_value/exc_traceback 的 args。不驱动它，删产品
        # 代码里 `threading.excepthook = thread_hook` 那一行本用例仍会绿（真缺口）。
        try:
            raise ValueError("子线程炸了")
        except ValueError as exc:
            args = types.SimpleNamespace(exc_type=type(exc), exc_value=exc,
                                        exc_traceback=exc.__traceback__)
            threading.excepthook(args)
        text = target.read_text(encoding="utf-8")
        assert "ValueError" in text and "子线程炸了" in text
    finally:
        sys.excepthook, threading.excepthook = old, old_thread
