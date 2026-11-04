"""兜底路径的价值在于页面尺寸就是纸张尺寸，可用点数反验。"""
import re
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
img2pdf = pytest.importorskip("img2pdf")
from PIL import Image as PILImage  # noqa: E402

from photoprint.core import specs  # noqa: E402
from photoprint.win import pdf_export  # noqa: E402


def test_mm_to_pt():
    assert pdf_export.mm_to_pt(25.4) == pytest.approx(72.0)
    assert pdf_export.mm_to_pt(89.0) == pytest.approx(252.283, abs=0.01)
    assert pdf_export.mm_to_pt(127.0) == pytest.approx(360.0, abs=0.01)


def _mediabox(data: bytes):
    m = re.search(rb"MediaBox\s*\[([\d.\s]+)\]", data)
    assert m, "PDF 里找不到 MediaBox"
    return [float(x) for x in m.group(1).split()]


def test_export_pdf_page_size_equals_3r(tmp_path):
    a4 = specs.find_spec("3R")
    img = PILImage.new("RGB", (89, 127), (255, 0, 0))
    out = pdf_export.export_pdf([img], a4, tmp_path / "p.pdf")
    box = _mediabox(Path(out).read_bytes())
    assert box[0] == 0 and box[1] == 0
    assert box[2] == pytest.approx(252.283, abs=1.0)
    assert box[3] == pytest.approx(360.0, abs=1.0)


def test_export_pdf_for_a4(tmp_path):
    img = PILImage.new("RGB", (210, 297), (0, 0, 255))
    out = pdf_export.export_pdf([img], specs.find_spec("A4"), tmp_path / "a.pdf")
    box = _mediabox(Path(out).read_bytes())
    assert box[2] == pytest.approx(595.276, abs=1.0)
    assert box[3] == pytest.approx(841.89, abs=1.0)


def test_export_multiple_pages(tmp_path):
    imgs = [PILImage.new("RGB", (210, 297), (0, 255, 0)) for _ in range(3)]
    out = pdf_export.export_pdf(imgs, specs.find_spec("A4"), tmp_path / "m.pdf")
    data = Path(out).read_bytes()
    assert data.count(b"MediaBox") >= 3


def test_empty_input_rejected(tmp_path):
    with pytest.raises(ValueError, match="没有"):
        pdf_export.export_pdf([], specs.find_spec("A4"), tmp_path / "e.pdf")
