"""等尺寸 PDF 导出：直打被驱动拒绝时的兜底路径。

页面尺寸严格等于纸张物理尺寸，用户在 Acrobat/SumatraPDF 里选"实际大小/100%"
打印即可复现排版；不依赖程序化 DEVMODE。
"""
from __future__ import annotations

import io
from pathlib import Path

import img2pdf
from PIL import Image  # noqa: F401  接口文档性导入：images 元素即 PIL.Image

# 换算唯一入口在 units（T13 评审 I-1：不得在消费模块自带第二套 mm→pt 公式）；
# re-export 保住 pdf_export.mm_to_pt 的既有测试入口
from photoprint.core.units import MM_TO_PT, mm_to_pt  # noqa: F401


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
