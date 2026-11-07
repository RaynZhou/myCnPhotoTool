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


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """cli.main 自己 new `store.Store()`，吃的是默认配置路径（%APPDATA%）。

    不隔离的话测试钉的边距数字与遮罩带宽度就取决于开发机上那份 papers.json：
    界面一旦跑过驱动实测并 override_margins + save()（写的就是同一个文件），
    pytest 会因与本改动无关的原因变红。`Store.__init__` 在调用时才读模块全局，
    所以 patch 该变量就能顶住。
    """
    monkeypatch.setattr(store, "DEFAULT_PATH", tmp_path / "papers.json")


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


def test_id_photos_are_not_rotated(st):
    """证件照是 cell：拼版必须禁旋转（全局约束 allow_rotate=False）。

    旧写法三个 pack 调用都吃默认 allow_rotate=True，A4+ID1 gap2 被装成
    63 格、其中 42 张横放，既不是 56 也不是证件照该有的朝向（终审 I1）。
    """
    plan, _mode = cli.build_plan_jobs(st, "A4", "ID1", 2.0,
                                      modes.DEFAULT_BLEED_MM, None, False)
    assert plan.count == 56
    assert not any(c.rotated for c in plan.cells)


def test_paper_role_cells_still_rotate(st):
    """纸类拼版（4R）不受影响：旋转仍是合法策略，不得被上式一起禁掉。"""
    plan, _mode = cli.build_plan_jobs(st, "A4", "4R", 0.0,
                                      modes.DEFAULT_BLEED_MM, None, False)
    assert any(c.rotated for c in plan.cells)


def _four_red_photos(tmp_path):
    from PIL import Image

    photos = []
    for i in range(4):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (255, 0, 0)).save(p)
        photos.append(str(p))
    return photos


def test_main_out_png_has_no_unprintable_mask(tmp_path):
    """遮罩是界面诚实性用的，导出进相纸就是缺陷。

    探针取 (1, ·) / (·, 1)：A4 的左/上边距是 3.4/3.0mm，dpi 25.4 下遮罩带
    只覆盖 0..2 像素（矩形右下角减 1），取 x=3 会探到带外——带外本来就是白的，
    这条测试就会无论如何都绿，遮罩没关也报不了。顶缘探针取 w//4 而不是 w//2：
    A4+3R 的列缝正好在 105mm（= w//2），虽当前从格上沿起画填不到 y=1，但也不必
    把像素断言寄在切缝长度规则上。
    """
    from PIL import Image

    out = tmp_path / "page.png"
    code = cli.main(["--photos", *_four_red_photos(tmp_path), "--sheet", "A4",
                     "--cell", "3R", "--dpi", "25.4", "--out", str(out)])
    assert code == 0
    img = Image.open(out)
    w, h = img.size
    assert img.getpixel((1, h // 4)) == (255, 255, 255), "左缘不得有灰遮罩带"
    assert img.getpixel((w // 4, 1)) == (255, 255, 255), "上缘不得有灰遮罩带"


def test_main_mask_flag_keeps_mask(tmp_path):
    """默认关不等于删功：调试时 `--mask` 必须还能把遮罩拿回来。"""
    from PIL import Image

    out = tmp_path / "page.png"
    code = cli.main(["--photos", *_four_red_photos(tmp_path), "--sheet", "A4",
                     "--cell", "3R", "--dpi", "25.4", "--mask",
                     "--out", str(out)])
    assert code == 0
    img = Image.open(out)
    w, h = img.size
    # (210, 210, 210) = MASK_RGB(150) 以 alpha 110 压在白纸上的合成值
    assert img.getpixel((1, h // 4)) == (210, 210, 210)
    assert img.getpixel((w // 4, 1)) == (210, 210, 210)


def test_build_plan_jobs_is_still_positional(st):
    """历史调用形状不得变：本文件 6 处调用全按 7 个位置参数（无关键字）调它。

    还得钉格子几何：gap 与 bleed 是相邻同类型的 float 位置参数，转发时写错
    顺序不会炸签名，只会静默换掉出血与间距。Task 4 退役对拍测试后，这条是
    唯一守这层转发映射的测试——只钉 (count, mode) 的话 4 格照样是 4 格，
    参数换了位也绿。（实测：正确 (95.0, 105.0)，互换 gap/bleed → (89.0, 106.5)）
    """
    plan, mode = cli.build_plan_jobs(st, "A4", "3R", 0.0,
                                     modes.DEFAULT_BLEED_MM, None, False)
    assert plan.count == 4
    assert mode == modes.BLEED_TRIM
    assert (plan.cells[0].w_mm, plan.cells[1].x_mm) == (95.0, 105.0)


def test_cli_stdout_note_wording_is_frozen(tmp_path, capsys):
    """全局约束：“cli 输出文案逐字不变”。重构前就应该通过——
    它是逐字冻结的回归锁，不是 RED 步骤：界面用的 `Job.note` 按 margin_source
    分档，措辞与本句不同，cli 这一侧必须自己钉住。

    钉整行而不只钉 note 子句：“每页 N 格 / 共 M 页”本轮从 `plan.count` /
    `len(_pages(...))` 换成了 `job.count` / `len(render_all(...))`，只钉后半句
    的话这两处漂了测试也不红。两档分支（白边 / 出血）都得钉。
    """
    photos = _four_red_photos(tmp_path)
    # 不传 --gap：格数跟的是 cli 自己的默认值 0.0（72），不是对拍用的 2.0（56）
    assert cli.main(["--photos", *photos, "--sheet", "A4", "--cell", "ID1",
                     "--dpi", "25.4"]) == 0
    assert capsys.readouterr().out == (
        "纸张 A4，每页 72 格，共 1 页。将保留白边：依规格约 "
        "上3.0/下5.0/左3.4/右3.4mm（未经真机校准）\n")

    assert cli.main(["--photos", *photos, "--sheet", "A4", "--cell", "3R",
                     "--dpi", "25.4"]) == 0
    assert capsys.readouterr().out == (
        "纸张 A4，每页 4 格，共 1 页。"
        "需人工裁切：沿灰线切开后即为 89×127mm 成品\n")


# ---------- 驱动表单绑定（spec 2026-11-07） ----------


def test_print_passes_measured_forms(tmp_path, monkeypatch):
    """CLI 直打也走同一探测：把实测表单交给 print_job。"""
    from PIL import Image

    from photoprint.win import forms, gdi_print

    p = tmp_path / "0.jpg"
    Image.new("RGB", (400, 200), (10, 20, 30)).save(p)
    form = forms.PaperForm(126, "L 89x127mm", 88.98, 127.0)
    seen = {}
    monkeypatch.setattr(forms, "measure", lambda api, printer: [form])

    def fake_print_job(api, printer, port, images, sheet, dpi, dm=None, forms=None):
        seen["forms"] = forms
        return {"ok": True, "pages": len(images), "message": ""}

    monkeypatch.setattr(gdi_print, "print_job", fake_print_job)
    assert cli.main(["--photos", str(p), "--sheet", "3R", "--cell", "3R",
                     "--dpi", "25.4", "--print", "--printer", "P"]) == 0
    assert seen["forms"] == [form]


def test_print_survives_form_probe_failure(tmp_path, monkeypatch, capsys):
    """探测抛异常：仍直打（传空表），且 stdout 文案形状不变。"""
    from PIL import Image

    from photoprint.win import forms, gdi_print

    p = tmp_path / "0.jpg"
    Image.new("RGB", (400, 200), (10, 20, 30)).save(p)
    seen = {}

    def boom(api, printer):
        raise RuntimeError("device caps failed")

    monkeypatch.setattr(forms, "measure", boom)

    def fake_print_job(api, printer, port, images, sheet, dpi, dm=None, forms=None):
        seen["forms"] = forms
        return {"ok": True, "pages": len(images), "message": ""}

    monkeypatch.setattr(gdi_print, "print_job", fake_print_job)
    assert cli.main(["--photos", str(p), "--sheet", "3R", "--cell", "3R",
                     "--dpi", "25.4", "--print", "--printer", "P"]) == 0
    assert seen["forms"] == []
    assert "已发送 1 页" in capsys.readouterr().out
