"""用户配置读写：预设 + 覆盖差异 + 自建尺寸三者的合成。

真相源规则（后续任务与 M3 界面都依此行事）：
- 预设：specs.PAPER_PRESETS，papers.json 只存覆盖差异 overrides[key]；
- 自建尺寸：self._users 是唯一定本，raw["user_sizes"] 每次变更后由它重新序列化；
- 自建 key 的边距走 _users 记录本身，不写 overrides —— overrides 对自建 key
  永不生效（resolve 里 _users 短路在前），写进去就是死数据。

写盘失败（权限、被占用）时内存修改依然生效并返回 False，
调用方必须在状态栏提示"本次设置未持久化"，不得静默丢弃。
"""
from __future__ import annotations

import copy
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from photoprint.core import specs

# 自建尺寸不得用这些 key：_users 在 resolve 里短路在前，重名会静默遮蔽预设
PRESET_KEYS = frozenset(s.key for s in specs.PAPER_PRESETS + specs.CELL_PRESETS)


def default_path() -> Path:
    """`%APPDATA%\\PhotoPrint\\papers.json`。

    用环境变量而不是 `Path.home() / "AppData" / "Roaming"`：前者尊重重定向与
    非系统盘部署，后者只在系统盘就是 C: 时才对；取不到 APPDATA 才退回家目录推算。
    """
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "PhotoPrint" / "papers.json"


DEFAULT_PATH = default_path()


def _empty_raw() -> dict:
    return {"overrides": {}, "user_sizes": [], "last_job": {}}


def _norm_margins(m: specs.Margins) -> specs.Margins:
    """归一为 float：SpinBox 常交来 int，混进去会让同一份配置里出现 3 与 3.0 两种形状。"""
    return specs.Margins(float(m.top), float(m.bottom), float(m.left), float(m.right))


def _margins_from_dict(m: dict) -> specs.Margins:
    """缺字段按规格默认补齐，与 _from_dict 走同一条路径。"""
    return specs.Margins(float(m.get("top", 3.0)), float(m.get("bottom", 5.0)),
                         float(m.get("left", 3.4)), float(m.get("right", 3.4)))


class Store:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self.raw: dict = _empty_raw()
        self._users: dict[str, specs.SizeSpec] = {}

    def load(self) -> None:
        """读盘。任何损坏都降级成"这份没有"，结对不抛。

        只挡语法错不够：用户手改过的 papers.json 多半是语法对、形状错
        （顶层是 list、user_sizes 里混进字符串、条目缺 label），那些必须在
        这里一次性围住，否则坏配置会把启动流程整个卡死。
        """
        try:
            disk = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            disk = None
        if not isinstance(disk, dict):
            disk = {}
        self.raw = _empty_raw()
        overrides = disk.get("overrides")
        if isinstance(overrides, dict):
            # 逐条也要形状对，否则 resolve 会在后面某次调用里招
            self.raw["overrides"] = {
                k: v for k, v in overrides.items()
                if isinstance(v, dict) and isinstance(v.get("margins_mm"), dict)}
        last_job = disk.get("last_job")
        self.raw["last_job"] = last_job if isinstance(last_job, dict) else {}
        items = disk.get("user_sizes")
        self._users = {}
        for item in items if isinstance(items, list) else []:
            try:
                spec = _from_dict(item)
            except (KeyError, TypeError, ValueError):
                continue  # 单条坏记录不牵连其余
            self._users[spec.key] = spec
        self._sync_user_sizes()

    def resolve(self, key: str) -> specs.SizeSpec:
        if key in self._users:
            return copy.deepcopy(self._users[key])
        base = specs.find_spec(key)
        ov = self.raw["overrides"].get(key)
        if not ov:
            return copy.deepcopy(base)
        return specs.SizeSpec(
            base.key, base.label, base.w_mm, base.h_mm, base.role, base.origin,
            base.borderless,
            _margins_from_dict(ov["margins_mm"]),
            ov.get("margin_source", "spec"),
            base.driver_paper_name, base.driver_paper_code,
        )

    def override_margins(self, key: str, margins: specs.Margins, source: str) -> None:
        m = _norm_margins(margins)
        user = self._users.get(key)
        if user is not None:
            # 自建尺寸的真相源只有一份：直接改它自己的记录
            user.margins = m
            user.margin_source = source
            self._sync_user_sizes()
            return
        self.resolve(key)  # 未知 key 在这里抛错，避免写入无效覆盖
        self.raw["overrides"][key] = {
            "margins_mm": {"top": m.top, "bottom": m.bottom,
                           "left": m.left, "right": m.right},
            "margin_source": source,
            "updated_at": date.today().isoformat(),
        }

    def add_user_size(self, spec: specs.SizeSpec) -> None:
        if not spec.key or spec.key in PRESET_KEYS:
            raise ValueError(f"自建尺寸 key 非法：{spec.key!r}（不得为空，不得与预设重名）")
        ok, msg = specs.custom_size_is_legal(spec.w_mm, spec.h_mm)
        if not ok:
            raise ValueError(msg)
        # 存副本而不是改入参：就地改 spec 会让调用方手里的对象和 _users 里的
        # 副本各自演化（双真相源），下一次 save() 写的是谁的看见都不一定
        stored = copy.deepcopy(spec)
        stored.w_mm, stored.h_mm = float(spec.w_mm), float(spec.h_mm)
        stored.margins = _norm_margins(spec.margins)
        # 自建尺寸一律走自定义送纸，无边距能力强制关闭
        stored.origin = "user"
        stored.borderless = False
        stored.role = "paper"
        stored.margin_source = "spec"
        self._users[stored.key] = stored
        self._sync_user_sizes()

    def _sync_user_sizes(self) -> None:
        self.raw["user_sizes"] = [_to_dict(s) for s in self._users.values()]

    def save(self) -> bool:
        """先写同目录 .tmp 再 os.replace：不让写入中途被杀留下一半 papers.json。

        TypeError/ValueError 也归入失败：不序列化得了的值（NaN 以外的对象、
        手滑传进来的路径对象）归调用方错，但对用户而言现象与写盘失败相同。
        """
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(self.raw, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except (OSError, TypeError, ValueError):
            return False
        return True


def _to_dict(s: specs.SizeSpec) -> dict:
    # driver_paper_* 不落盘：自建尺寸没有驱动纸张名，那个字段只对预设有意义
    return {
        "key": s.key, "label": s.label, "w_mm": s.w_mm, "h_mm": s.h_mm,
        "role": s.role, "origin": s.origin, "borderless": s.borderless,
        "margins_mm": {"top": s.margins.top, "bottom": s.margins.bottom,
                       "left": s.margins.left, "right": s.margins.right},
        "margin_source": s.margin_source,
    }


def _from_dict(d: dict) -> specs.SizeSpec:
    """磁盘记录 → 规格。缺字段补默认，类型错就抛（由 load() 逐条兜住）。

    role / origin / borderless 三个字段不采信磁盘值：本项目里自建尺寸只能当
    纸，且自定义送纸必然留白边（规格第 2 节硬事实）。
    """
    return specs.SizeSpec(
        d["key"], d["label"], float(d["w_mm"]), float(d["h_mm"]),
        "paper", "user", False,
        _margins_from_dict(d.get("margins_mm") or {}),
        d.get("margin_source", "spec"),
    )
