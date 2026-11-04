"""等尺寸 PDF 导出：直打被驱动拒绝时的兜底路径。

页面尺寸严格等于纸张物理尺寸，用户在 Acrobat/SumatraPDF 里选"实际大小/100%"
打印即可复现排版；不依赖程序化 DEVMODE。
"""
from __future__ import annotations

import io
from pathlib import Path

import img2pdf
from PIL import Image

MM_TO_PT = 72.0 / 25.4


def mm_to_pt(mm: float) -> float:
    return mm * MM_TO_PT


def export_pdf(images, sheet, out_path):
    """把已渲染的页面图导出为等尺寸 PDF。"""
    if not images:
        raise ValueError("没有可导出的页面")
    chunks = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        chunks.append(buf.getvalue())
    layout = img2pdf.get_layout_fun((mm_to_pt(sheet.w_mm), mm_to_pt(sheet.h_mm)))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img2pdf.convert(*chunks, layout_fun=layout))
    return out_path
