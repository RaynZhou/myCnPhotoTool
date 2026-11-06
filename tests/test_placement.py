"""放置内核：库/放置解耦、逐格旋转、页数派生、持久化与迁移。offscreen。"""
import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QElapsedTimer, QEventLoop  # noqa: E402

from photoprint.app.main_window import MainWindow  # noqa: E402
from photoprint.core import store  # noqa: E402


def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s


@pytest.fixture(autouse=True)
def _no_leaked_threads(qapp):
    yield
    wins = [w for w in qapp.topLevelWidgets() if isinstance(w, MainWindow)]
    for w in wins:
        w._debounce.stop()
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < 3000:
        qapp.processEvents(QEventLoop.AllEvents, 50)
        if not any(w._thread is not None and w._thread.isRunning() for w in wins):
            break
    for w in wins:
        w.close()
    qapp.processEvents(QEventLoop.AllEvents, 100)


def _settle(window, qapp, timeout_ms=5000):
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < timeout_ms:
        qapp.processEvents(QEventLoop.AllEvents, 50)
        if window._thread is None:
            return
        if not window._thread.isRunning():
            qapp.processEvents(QEventLoop.AllEvents, 50)
            return
    pytest.fail("预览线程未在预期时间内停下")


def _make_photos(tmp_path, n=4):
    paths = []
    for i in range(n):
        p = tmp_path / f"{i}.jpg"
        Image.new("RGB", (400, 200), (200 - 30 * i, 30, 40)).save(p)
        paths.append(str(p))
    return paths


def _fill(window, tmp_path, n=4):
    """append 进库后顺序 place 到槽 0..n-1——复现旧“自动填充”对既有测试的意义。"""
    for p in _make_photos(tmp_path, n):
        window.append_photo(p)
    for i in range(n):
        window.place(i, i)
    window._refresh()


def test_append_does_not_auto_place(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    for p in _make_photos(tmp_path, 3):
        w.append_photo(p)
    w._refresh()
    assert len(w.pool) == 3 and w.placements == {}
    assert all(ph is None for ph in w.job.photos)        # 入列不进版面


def test_place_materializes_into_job(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])
    assert w.place(0, 0) is True
    w._refresh()
    assert w.job.photos[0] is w.pool[0]["img"]
    assert sum(1 for ph in w.job.photos if ph is not None) == 1


def test_same_photo_repeatable_multiple_slots(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])
    w.place(0, 0)
    w.place(2, 0)
    w._refresh()
    assert w.job.photos[0] is w.pool[0]["img"]
    assert w.job.photos[2] is w.pool[0]["img"]           # 引用不消耗
    assert w.placements[0] == w.placements[2] == 0


def test_place_out_of_range_fails(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])
    assert w.place(0, 5) is False                        # 库下标越界
    assert w.placements == {}


def test_rotate_is_per_cell_only(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)                                   # 4 张顺序入槽
    w._current_cell = 1
    w.rotate_cell(1)
    assert w.cell_rot == {1: 90}                          # 只这格
    w._refresh()
    assert w.job.rotations[1] == 90 and w.job.rotations[0] == 0


def test_rotate_without_current_cell_prompts(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w._current_cell = None
    before = dict(w.cell_rot)
    w._on_rotate()
    assert w.cell_rot == before
    assert "请先点选版面中已放图的格" in w.statusBar().currentMessage()


def test_clear_cell_empties_slot(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w.clear_cell(0)
    w._refresh()
    assert 0 not in w.placements
    assert w.job.photos[0] is None


def test_layout_count_change_clears_placements(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    assert w.placements
    w._select_by_data(w.cell_box, "5R")                # 换格子规格 → 每页格数变
    w._refresh()
    assert w.placements == {} and w._pages == 1
    assert "布局已变" in w.statusBar().currentMessage()


def test_next_page_extends_and_prev_shrinks(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=1)
    pages0 = w._pages
    w._go_page(1)                                        # 末页之后 → 追加空页
    assert w._pages == pages0 + 1
    w._go_page(-1)                                       # 离开空末页 → 收缩
    assert w._pages == pages0


def test_clear_button_wipes_pool_and_placements(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w._on_clear_photos()
    assert w.pool == [] and w.placements == {} and w.cell_rot == {}
    assert w._pages == 1 and w.photo_list.count() == 0


def test_persist_roundtrip_new_schema(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path, n=2)
    w._current_cell = 1
    w.rotate_cell(1)
    s2 = _store(tmp_path)
    w.st = s2                                            # 换新存储再落盘
    w.save_last_job()
    w2 = MainWindow(st=s2)
    assert len(w2.pool) == 2
    assert w2.placements == {0: 0, 1: 1}
    assert w2.cell_rot.get(1) == 90


def test_migration_sequential_from_legacy_rotations(qapp, tmp_path):
    """旧 last_job（photo_paths+rotations、无 placements）→ 顺序重放、逐格旋转。"""
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": [90, 180]})
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert len(w.pool) == 2
    assert w.placements == {0: 0, 1: 1}
    assert w.cell_rot == {0: 90, 1: 180}
    w._refresh()
    assert w.job.rotations[0] == 90 and w.job.rotations[1] == 180


def test_migration_bad_rotations_all_zero(qapp, tmp_path):
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": [90, "x"]})             # 含坏项 → 整体不恢复
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert w.cell_rot == {}                              # 全 0
    assert w.placements == {0: 0, 1: 1}                  # 顺序放置仍成立


def test_migration_overlong_rotations_truncated(qapp, tmp_path):
    s = _store(tmp_path)
    s.set_last_job({"sheet_key": "A4", "cell_key": "3R",
                    "photo_paths": _make_photos(tmp_path, 2),
                    "rotations": [90, 180, 270, 45]})     # 超长 → 截到库长 2
    s.save()
    w = MainWindow(st=_store(tmp_path))
    assert w.cell_rot == {0: 90, 1: 180}


def test_rebuild_injects_geometry(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    _settle(w, qapp)
    assert len(w.preview._cell_rects_px) == w.job.count   # 预览拿到当页格框


def test_click_places_selected_pool_photo(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])          # 库只 1 张，未放置
    w._refresh()
    w._on_photo_clicked(w.photo_list.item(0))            # 点选库图作放置源
    count = w._count_last
    w._on_cell_clicked(2)                                  # 第 1 页点第 3 格
    assert w.placements == {2: 0}                          # 槽位 = 0*count+2
    w.page_index = 1                                       # 翻到第 2 页再点：槽位须含页偏移
    w._on_cell_clicked(2)
    assert w.placements == {2: 0, count + 2: 0}            # 页内序 → 全局槽 = page*count+pos
    assert w._current_cell == count + 2


def test_click_without_selection_only_selects(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    assert w._place_source is None                     # 默认无放置源
    before = dict(w.placements)
    w._on_cell_clicked(1)
    assert w.placements == before                          # 无库选中→不改放置
    assert w._current_cell == 1


def test_clear_cell_button_exists_and_clears(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)
    w._current_cell = 1
    btn = w.findChild(type(w.export_btn), "clear_cell_btn")
    assert btn is not None
    btn.click()
    assert 1 not in w.placements and 1 not in w.cell_rot


def test_highlight_only_when_selected_cell_on_current_page(qapp, tmp_path):
    """选中格不在当前页 → 不高亮（翻页会弃选中，此处直接置位验证映射护栏）。"""
    w = MainWindow(st=_store(tmp_path))
    _fill(w, tmp_path)                       # count=4
    count = w._count_last
    w.page_index = 0
    w._current_cell = count + 1              # 选中格在第 2 页
    w._highlight_current_cell()
    assert w.preview._current_cell is None   # 不在当前页 → 不高亮
    w._current_cell = 1                      # 选中格回到当前页
    w._highlight_current_cell()
    assert w.preview._current_cell == 1


def test_reclick_selected_photo_deselects(qapp, tmp_path):
    """照片列表无专门取消入口的补位：再次点已选中的那张 → 取消放置源，
    此后点版面格从“放置”变回“纯选中”（供逐格旋转/清空格）。"""
    w = MainWindow(st=_store(tmp_path))
    w.append_photo(_make_photos(tmp_path, 1)[0])
    w._refresh()
    item = w.photo_list.item(0)
    w._on_photo_clicked(item)                    # 第一次点：选为放置源
    assert w._place_source == 0
    w._on_cell_clicked(2)
    assert w.placements.get(2) == 0              # 放置生效
    w._on_photo_clicked(item)                    # 再次点同一张：取消
    assert w._place_source is None
    w._on_cell_clicked(1)
    assert 1 not in w.placements                 # 不再放置
    assert w._current_cell == 1                  # 退化为纯选中
