"""papers.json 只存差异，升级预设不得冲掉用户标定。"""
import json
from pathlib import Path

import pytest

from photoprint.core import specs, store


@pytest.fixture
def tmp_store(tmp_path):
    return store.Store(tmp_path / "papers.json")


def test_resolve_without_override_returns_preset(tmp_store):
    tmp_store.load()
    s = tmp_store.resolve("3R")
    assert s.margins.top == 3.0
    assert s.margin_source == "spec"


def test_override_margins_upgrades_source_and_persists(tmp_store):
    tmp_store.load()
    tmp_store.override_margins("3R", specs.Margins(2.8, 5.2, 3.5, 3.5), "calibrated")
    assert tmp_store.save() is True
    disk = json.loads(Path(tmp_store.path).read_text(encoding="utf-8"))
    assert disk["overrides"]["3R"]["margin_source"] == "calibrated"
    assert disk["overrides"]["3R"]["margins_mm"]["bottom"] == 5.2

    again = store.Store(tmp_store.path)
    again.load()
    s = again.resolve("3R")
    assert s.margin_source == "calibrated"
    assert s.margins.left == 3.5


def test_file_only_stores_difference_not_whole_preset(tmp_store):
    tmp_store.load()
    tmp_store.override_margins("3R", specs.Margins(3.0, 5.0, 3.4, 3.4), "probed")
    tmp_store.save()
    disk = json.loads(Path(tmp_store.path).read_text(encoding="utf-8"))
    assert set(disk["overrides"]["3R"]) == {"margins_mm", "margin_source", "updated_at"}
    assert "w_mm" not in disk["overrides"]["3R"]


def test_user_size_rejects_illegal(tmp_store):
    tmp_store.load()
    bad = specs.SizeSpec("user-12", "12寸", 254.0, 305.0, "paper", "user",
                         False, specs.Margins(), "spec")
    with pytest.raises(ValueError, match="215.9"):
        tmp_store.add_user_size(bad)


def test_user_size_forces_borderless_false(tmp_store):
    tmp_store.load()
    s = specs.SizeSpec("user-4d", "4D 自建", 100.0, 148.0, "paper", "user",
                       True, specs.Margins(), "spec")
    tmp_store.add_user_size(s)
    got = tmp_store.resolve("user-4d")
    assert got.origin == "user"
    assert got.borderless is False  # 自定义尺寸不可能无边距，用户意愿不予采纳


def test_save_failure_keeps_memory_effect(tmp_path):
    blocked = tmp_path / "dir.json"
    blocked.mkdir()  # 目录占位，写文件必然失败
    st = store.Store(blocked)
    st.load()
    st.override_margins("3R", specs.Margins(1, 2, 3, 4), "calibrated")
    assert st.save() is False
    assert st.resolve("3R").margin_source == "calibrated"


def test_corrupt_file_falls_back_to_empty(tmp_store):
    Path(tmp_store.path).write_text("{ not json", encoding="utf-8")
    tmp_store.load()
    assert tmp_store.resolve("3R").margin_source == "spec"
