"""rotations 必须原样透传到渲染层：编排层不得自己换算或归一角度（几何禁则）。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")

from PIL import Image  # noqa: E402

from photoprint import jobs  # noqa: E402
from photoprint.core import render, store  # noqa: E402


@pytest.fixture
def st(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


def _photo():
    return Image.new("RGB", (100, 100), (200, 30, 30))


def test_job_rotations_defaults_to_empty_tuple(st):
    job = jobs.build_job(st, [_photo()] * 4, "A4", "ID1", gap_mm=2.0)
    assert job.rotations == ()


def test_build_job_keeps_rotations_verbatim(st):
    job = jobs.build_job(st, [_photo()] * 4, "A4", "ID1", gap_mm=2.0,
                         rotations=(90, -90, 45, "x"))
    assert job.rotations == (90, -90, 45, "x")


def test_job_render_forwards_rotations_without_touching(st, monkeypatch):
    """与 test_build_job_passes_percentage_through 同款 spy：只拦一层看真参数。"""
    seen = {}
    real = render.render_page

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(render, "render_page", spy)
    job = jobs.build_job(st, [_photo()] * 4, "A4", "ID1", gap_mm=2.0,
                         rotations=(90, 0, 0, 0))
    job.render(0, 25.4)
    assert seen["rotations"] == (90, 0, 0, 0)


def test_rotation_changes_rendered_pixels(st):
    """必须是方向可辨的图：简报原方的 100×100 纯色图转 90° 逐像素不变，
    该断言永远红（计划自身的测试 bug，实测后改用 2:1 横图）。"""
    ph = Image.new("RGB", (200, 100), (200, 30, 30))
    a = jobs.build_job(st, [ph] * 4, "A4", "ID1", gap_mm=2.0)
    b = jobs.build_job(st, [ph] * 4, "A4", "ID1", gap_mm=2.0,
                       rotations=(90,) + (0,) * 3)
    assert a.render(0, 25.4).tobytes() != b.render(0, 25.4).tobytes()


def test_rotations_do_not_leak_across_pages(st):
    """分页错位回归锁：render_page 收到按页切片的 photos，角度必须同窗切片。

    若整表直传，rotations[i] 会对到第 i%n 张照片：把唯一的 90° 放在首页
    首格，第二页首格本应原样，泄漏时却被转——本用例钉住这点。
    （控制器对简报 Step 3 的裁决性偏差，变异实测：不切片时此例红；
    简报表内测试全是单页场景，钉不住这条。）"""
    ph = Image.new("RGB", (200, 100), (200, 30, 30))
    n = jobs.build_job(st, [], "A4", "ID1", gap_mm=2.0).count
    job = jobs.build_job(st, [ph] * (2 * n), "A4", "ID1", gap_mm=2.0,
                         rotations=(90,) + (0,) * (2 * n - 1))
    plain = jobs.build_job(st, [ph] * (2 * n), "A4", "ID1", gap_mm=2.0)
    assert job.page_count == 2 and plain.page_count == 2
    assert job.render(1, 25.4).tobytes() == plain.render(1, 25.4).tobytes()
