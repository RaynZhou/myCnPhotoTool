"""GUI 与 CLI 必须出同一张图：共用 jobs 编排的机器化验证。

同时钉住导出遮罩口径：两边产物的四边都不得是 (210, 210, 210)。
测试图本脚本自造，不依赖任何已存在的目录。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

# 本目录脚本以 `python _lab/xxx.py` 直跑时 sys.path[0] 是 _lab/、非仓库根，
# 需显式把根加进来（与 m1m2_check.py 同法），否则 `import photoprint` 当场失败。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.core import store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_lab" / "out"
DPI = 300.0


def make_photos(tmp: Path):
    paths = []
    for i in range(2):
        p = tmp / f"p{i}.jpg"
        Image.new("RGB", (1200, 800), (200 - 60 * i, 90, 40 + 50 * i)).save(p)
        paths.append(str(p))
    return paths


def gui_page(paths):
    """界面走的那条路：build_job + 单页 render。"""
    st = store.Store()
    st.load()
    photos = [jobs.load_photo(p) for p in paths]
    job = jobs.build_job(st, photos, "A4", "3R", bleed_mm=3.0)
    return job.render(0, DPI, show_mask=False)


def cli_page(paths, tmp: Path):
    """CLI 走的那条路：子进程跑真实命令行，不碰内部函数。"""
    out = tmp / "cli.png"
    subprocess.run([sys.executable, "-m", "photoprint.cli", "--photos", *paths,
                    "--sheet", "A4", "--cell", "3R", "--dpi", str(int(DPI)),
                    "--out", str(out)], check=True, cwd=str(ROOT))
    return Image.open(out)


def edge_is_clean(img) -> bool:
    w, h = img.size
    return (img.getpixel((3, h // 2)) != (210, 210, 210)
            and img.getpixel((w // 2, 3)) != (210, 210, 210))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        paths = make_photos(tmp)
        a, b = gui_page(paths), cli_page(paths, tmp)
        same_size = a.size == b.size
        same_pixels = same_size and list(a.getdata()) == list(b.getdata())
        clean = edge_is_clean(a) and edge_is_clean(b)
        a.save(OUT / "parity_gui.png")
        b.save(OUT / "parity_cli.png")
    print(f"同尺寸 {same_size} · 同像素 {same_pixels} · 四边无遮罩 {clean}")
    return 0 if (same_size and same_pixels and clean) else 1


if __name__ == "__main__":
    raise SystemExit(main())
