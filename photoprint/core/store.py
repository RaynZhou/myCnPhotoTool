"""用户配置读写：预设 + 覆盖差异 + 自建尺寸三者的合成。

写盘失败（权限、被占用）时内存修改依然生效并返回 False，
调用方必须在状态栏提示"本次设置未持久化"，不得静默丢弃。
"""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import Optional

from photoprint.core import specs

DEFAULT_PATH = Path.home() / "AppData" / "Roaming" / "PhotoPrint" / "papers.json"


class Store:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self.raw: dict = {"overrides": {}, "user_sizes": [], "last_job": {}}
        self._users: dict[str, specs.SizeSpec] = {}

    def load(self) -> None:
        try:
            self.raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.raw = {"overrides": {}, "user_sizes": [], "last_job": {}}
        self.raw.setdefault("overrides", {})
        self.raw.setdefault("user_sizes", [])
        self.raw.setdefault("last_job", {})
        self._users = {}
        for item in self.raw["user_sizes"]:
            self._users[item["key"]] = _from_dict(item)

    def resolve(self, key: str) -> specs.SizeSpec:
        if key in self._users:
            return copy.deepcopy(self._users[key])
        base = specs.find_spec(key)
        ov = self.raw["overrides"].get(key)
        if not ov:
            return copy.deepcopy(base)
        m = ov["margins_mm"]
        return specs.SizeSpec(
            base.key, base.label, base.w_mm, base.h_mm, base.role, base.origin,
            base.borderless,
            specs.Margins(m["top"], m["bottom"], m["left"], m["right"]),
            ov.get("margin_source", "spec"),
            base.driver_paper_name, base.driver_paper_code,
        )

    def override_margins(self, key: str, margins: specs.Margins, source: str) -> None:
        self.resolve(key)  # 未知 key 在这里抛错，避免写入无效覆盖
        self.raw["overrides"][key] = {
            "margins_mm": {"top": margins.top, "bottom": margins.bottom,
                           "left": margins.left, "right": margins.right},
            "margin_source": source,
            "updated_at": date.today().isoformat(),
        }

    def add_user_size(self, spec: specs.SizeSpec) -> None:
        ok, msg = specs.custom_size_is_legal(spec.w_mm, spec.h_mm)
        if not ok:
            raise ValueError(msg)
        # 自建尺寸一律走自定义送纸，无边距能力强制关闭
        spec.origin = "user"
        spec.borderless = False
        spec.role = "paper"
        spec.margin_source = "spec"
        self._users[spec.key] = spec
        self.raw["user_sizes"] = [_to_dict(s) for s in self._users.values()]

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.raw, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            return False
        return True


def _to_dict(s: specs.SizeSpec) -> dict:
    return {
        "key": s.key, "label": s.label, "w_mm": s.w_mm, "h_mm": s.h_mm,
        "role": s.role, "origin": s.origin, "borderless": s.borderless,
        "margins_mm": {"top": s.margins.top, "bottom": s.margins.bottom,
                       "left": s.margins.left, "right": s.margins.right},
        "margin_source": s.margin_source,
    }


def _from_dict(d: dict) -> specs.SizeSpec:
    m = d.get("margins_mm", {})
    return specs.SizeSpec(
        d["key"], d["label"], float(d["w_mm"]), float(d["h_mm"]),
        d.get("role", "paper"), d.get("origin", "user"),
        bool(d.get("borderless", False)),
        specs.Margins(m.get("top", 3.0), m.get("bottom", 5.0),
                      m.get("left", 3.4), m.get("right", 3.4)),
        d.get("margin_source", "spec"),
    )
