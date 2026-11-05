"""GUI 与 CLI 必须出同一张图：共用 jobs 编排的机器化验证。

同时钉住导出遮罩口径：两边产物的四边都得是纯白 (255, 255, 255)。
测试图本脚本自造，不依赖任何已存在的目录。

边界说明：GUI 侧是对界面那条编排（build_job → render(show_mask=False)）的**复述**，参数来源分三档：
出血 `bleed_mm` 与 main_window 真同源（都取 `modes.DEFAULT_BLEED_MM`）；导出 dpi 取
`jobs.DEFAULT_OUTPUT_DPI`，与界面下拉默认 300 **同值但不同源**（界面默认来自 `DPI_CHOICES` 字面量，
`DEFAULT_OUTPUT_DPI` 无生产消费者）；`store.Store()` 读真实 %APPDATA%（与界面校准同源、刻意一致，
若被改动会两边一起变而 fail-loud、不产假阳）。真实界面控件的默认值与导出 dpi/show_mask 仅由
tests/test_app_main_window.py 的 render_all spy 钉住「show_mask=False + dpi 跟随所选」，**不检查控件默认值**。
exe 二进制级与 CLI 的 **PDF** 像素一致需带交互桌面真机，不在本脚本范围（见 spec §11.5b / 终审）。
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
from photoprint.core import modes, store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_lab" / "out"
DPI = jobs.DEFAULT_OUTPUT_DPI
CLEAN_RGB = (255, 255, 255)   # 导出（show_mask=False）时四边应是纯白纸色
MASK_RGB = (210, 210, 210)    # 预览遮罩（show_mask=True）合成到纸边的灰遮罩色（见 core/render.py）


def make_photos(tmp: Path):
    paths = []
    for i in range(2):
        p = tmp / f"p{i}.jpg"
        Image.new("RGB", (1200, 800), (200 - 60 * i, 90, 40 + 50 * i)).save(p)
        paths.append(str(p))
    return paths


def build_gui_job(paths):
    """界面走的那条编排：build_job（出血与 main_window 同源，dpi 见模块 docstring 分档）+ 单页 render。"""
    st = store.Store()
    st.load()
    photos = [jobs.load_photo(p) for p in paths]
    return jobs.build_job(st, photos, "A4", "3R", bleed_mm=modes.DEFAULT_BLEED_MM)


def cli_page(paths, tmp: Path):
    """CLI 走的那条路：子进程跑真实命令行，不碰内部函数。"""
    out = tmp / "cli.png"
    subprocess.run([sys.executable, "-m", "photoprint.cli", "--photos", *paths,
                    "--sheet", "A4", "--cell", "3R", "--dpi", str(DPI),
                    "--out", str(out)], check=True, cwd=str(ROOT))
    return Image.open(out)


def edge_pixels(img):
    """产物四边中点各取一点：左、上、右、下。"""
    w, h = img.size
    return [img.getpixel(xy) for xy in
            [(3, h // 2), (w // 2, 3), (w - 4, h // 2), (w // 2, h - 4)]]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        paths = make_photos(tmp)
        job = build_gui_job(paths)
        a = job.render(0, DPI, show_mask=False)
        b = cli_page(paths, tmp)
        same_size = a.size == b.size
        same_pixels = same_size and a.mode == b.mode and a.tobytes() == b.tobytes()
        # 正对照：同图开遮罩再渲一次，必须先钉四边确为灰遮罩色；否则下面的
        # "导出四边纯白" 可能因探针落到带外 / 整体渲染坏掉而恒真空转。
        masked = job.render(0, DPI, show_mask=True)
        control_ok = all(px == MASK_RGB for px in edge_pixels(masked))
        masked.save(OUT / "parity_mask_control.png")   # 存正对照图，留人工复核探针落带内
        clean = (all(px == CLEAN_RGB for px in edge_pixels(a))
                 and all(px == CLEAN_RGB for px in edge_pixels(b)))
        a.save(OUT / "parity_gui.png")
        b.save(OUT / "parity_cli.png")
    # 上一行 cli_page 已让子进程按逐字冻结文案自行打印过，本行是本脚本结论。
    print(f"同尺寸 {same_size} · 同像素 {same_pixels} · 遮罩正对照 {control_ok} · 四边导出纯白 {clean}")
    return 0 if (same_size and same_pixels and control_ok and clean) else 1


if __name__ == "__main__":
    raise SystemExit(main())
