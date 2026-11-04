"""CLI 只做编排：几何决策必须来自 core，不在 cli 里重算。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from photoprint import cli  # noqa: E402
from photoprint.core import modes, store  # noqa: E402


@pytest.fixture
def st(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def test_default_mode_for_a4_3r_is_bleed_trim(st):
    plan, mode = cli.build_plan_jobs(st, "A4", "3R", 0.0, modes.DEFAULT_BLEED_MM,
                                     None, False)
    assert mode == modes.BLEED_TRIM
    assert plan.count == 4
    assert plan.cuts


def test_explicit_mode_is_respected(st):
    plan, mode = cli.build_plan_jobs(st, "A4", "3R", 0.0, 0.0,
                                     modes.FILL_PRINTABLE, False)
    assert mode == modes.FILL_PRINTABLE
    assert plan.count == 4


def test_illegal_bleed_on_3r_is_reported(st):
    with pytest.raises(ValueError, match="无边距"):
        cli.build_plan_jobs(st, "3R", "3R", 0.0, 3.0, modes.BLEED_TRIM, False)


def test_main_returns_2_when_no_photos(tmp_path, capsys):
    code = cli.main(["--sheet", "A4", "--cell", "3R",
                     "--out", str(tmp_path / "x.png")])
    assert code == 2
    assert "没有照片" in capsys.readouterr().err


def test_main_writes_png_with_exact_mm_size(tmp_path):
    from PIL import Image

    photos = []
    for i in range(4):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (i * 50, 30, 40)).save(p)
        photos.append(str(p))
    out = tmp_path / "page.png"
    code = cli.main(["--photos", *photos, "--sheet", "A4", "--cell", "3R",
                     "--dpi", "25.4", "--out", str(out)])
    assert code == 0
    img = Image.open(out)
    assert img.size == (210, 297)  # dpi 25.4 下 1px = 1mm，可直接核对物理尺寸


def test_main_writes_pdf_with_3r_box(tmp_path):
    import re
    from PIL import Image

    p = tmp_path / "0.jpg"
    Image.new("RGB", (400, 200), (10, 20, 30)).save(p)
    out = tmp_path / "page.pdf"
    code = cli.main(["--photos", str(p), "--sheet", "3R", "--cell", "3R",
                     "--dpi", "25.4", "--pdf", str(out)])
    assert code == 0
    m = re.search(rb"MediaBox\s*\[([\d.\s]+)\]", out.read_bytes())
    vals = [float(x) for x in m.group(1).split()]
    assert vals[2] == pytest.approx(252.283, abs=1.0)
    assert vals[3] == pytest.approx(360.0, abs=1.0)


def test_main_creates_out_parent_dirs(tmp_path):
    """README 首个示例直写 _lab/out/（git 不存空目录）：--out 必须自建父目录。"""
    from PIL import Image

    p = tmp_path / "0.jpg"
    Image.new("RGB", (400, 200), (1, 2, 3)).save(p)
    out = tmp_path / "deep" / "dir" / "page.png"
    code = cli.main(["--photos", str(p), "--sheet", "A4", "--cell", "3R",
                     "--dpi", "25.4", "--out", str(out)])
    assert code == 0
    assert out.exists()


def test_main_marks_first_page_only_for_multipage_out(tmp_path, capsys):
    """5 张在 A4+3R 下出 2 页：--out 只落第一页，必须明说，不得谎报全套已输出。"""
    from PIL import Image

    photos = []
    for i in range(5):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (i, 9, 9)).save(p)
        photos.append(str(p))
    out = tmp_path / "page.png"
    code = cli.main(["--photos", *photos, "--sheet", "A4", "--cell", "3R",
                     "--dpi", "25.4", "--out", str(out)])
    assert code == 0
    assert "仅第一页" in capsys.readouterr().out
