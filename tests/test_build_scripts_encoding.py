r"""守护 .ps1 交付物的 UTF-8 BOM：Windows PowerShell 5.1 读无 BOM 的 UTF-8 会按
系统 GBK 码页解码，脚本里的中文注释与全角标点（：（））会打断字符串字面量解析、
报 `字符串缺少终止符` ParserError（Task 9 首跑 build_exe.ps1 真踩过）。BOM 在 diff
里不可见，编辑器/工具可能无声剥掉——这条断言把它钉住，剥了就红。

字节级断言，跨平台稳定：BOM 是提交进仓库的固定前缀，任何机器读到的字节都一致。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS1 = [ROOT / "build_exe.ps1", ROOT / "_lab" / "check_exe.ps1"]

BOM = b"\xef\xbb\xbf"


def test_build_powershell_scripts_start_with_utf8_bom():
    for p in PS1:
        head = p.read_bytes()[:3]
        assert head == BOM, f"{p} 缺 UTF-8 BOM（前 3 字节={head!r}），PS5.1 会按 GBK 误读中文"
