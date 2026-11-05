# 逐张照片旋转 90°（M3-GUI 增量）设计

日期：2026-11-05　基线：`master` @ db553ce（gui-exe 已整枝合入）

## 0. 背景与决策来源

用户在 exe 实测：一张 1870×1071 的横图放进 A4 左上格子，"完整放入（留白）"
模式下画面被压得很小——照片转 90° 竖放才能占满格子高度。现有界面没有任何
逐图操作：格子朝向由装箱统一决定（`pack.allow_rotate`），且证件照类格子被全
局约束禁止旋转；`render.py` 的旋转逻辑只服务于"格子旋转装箱"，不是用户主动
旋转照片内容。

与用户逐问确认的决策（本文档不重开这些选择）：

1. **逐张旋转**：选中某张再转，同页其余照片不受影响；
2. **只转照片内容，格子与排版不变**（不动 `pack`，不推翻"证件照格不得旋转"
   的硬约束）；
3. **工具按钮触发**，每次顺时针 +90°，0→90→180→270→0 循环；
4. 实现落点取**方案 A**：旋转作为照片属性进入核心渲染层，预览与导出共用同
   一条渲染路径——"所见即所得是构造出来的"这一既有原则不得破坏。

本文档是决策完备的：实现者不需要再做产品选择，只需按条目落地。

## 1. 范围

做：

- `core/render.py`：`render_page` 新增 `rotations` 参数，逐格生效。
- `jobs.py`：`Job` 新增 `rotations` 字段；`build_job` 新增同名关键字参数。
- `app/main_window.py`：照片列表下加「旋转 90°」按钮 + 列表角度后缀显示。
- `last_job` 持久化新增 `rotations`，与 `photo_paths` 按下标一一对应。
- 相应脱机测试与 GUI 冒烟测试。

不做（明确排除，实现时不得顺手加）：

- 逆时针按钮、右键菜单、键盘快捷键（顺时针循环 4 次即回到原点，够用）。
- 多选批量旋转（`currentRow` 单行语义，多选交互留待有真实需求）。
- CLI 旋转参数：`cli.py` 行为与输出保持逐字冻结。
- 旋转参与装箱决策、格子朝向随照片变化（方案 C，已否决）。
- 角度任意输入（只允许 90 的整数倍）。

## 2. 语义模型与不变量

**生效照片**（effective photo）定义为原图按 `rotations[i]` 顺时针转好后的图：

```python
_TRANSPOSE_BY_ANGLE = {0: None, 90: Image.ROTATE_270,
                       180: Image.ROTATE_180, 270: Image.ROTATE_90}
```

（PIL 的 `ROTATE_270` 是顺时针 90°，与 `render.py` 现有旋转格用法同口径。）

渲染循环里 `photo → effective_photo` 一步发生在取 `photo.width/height` 之前，
其余逻辑（`cell_crop_box`、偏移换算、缩放、paste）一行不改。由此得到本设计
的核心不变量，测试必须钉住：

> **I-1**：`render_page(plan, photos, ..., rotations=[a])` 与
> `render_page(plan, [pre_rotated(photo, a)], ..., rotations=[])` 逐像素相同。

即"渲染时转"与"读图时就转好"等价，旋转不引入第二套几何路径。

**偏移语义**：水平/垂直微调仍是纸面方向、仍按本格 `(ow, oh)` 逐格换算，一条
规则都不改。照片旋转与格子旋转（`cell.rotated`）可叠加，叠加时顺序固定为
"先转照片、后走既有格子旋转路径"；`rotate_offset` 的换算对象是格子旋转，与
照片旋转无关。

**角度归一**：`rotations` 条目先 `% 360` 归一（Python 语义下 -90 → 270，合法
采纳）；归一后仍不在 {0, 90, 180, 270}（如 45），或根本转不了 int（字符串、
None）→ 按 0 处理，不抛错——旋转是增强项，不得让一次坏数据把渲染整页打死
（与 store 的"任何损坏降级成没有"同口径）。

**空格与长度**：`rotations` 长度可小于 `photos`（缺的按 0）；`photo is None`
的空格跳过渲染，与其下标角度无关。

## 3. 接口改动

```python
# core/render.py
def render_page(plan, photos, sheet, dpi, mode, show_mask=True,
                show_cut_lines=True, borderless_active=False,
                offset_pct=(0.0, 0.0), rotations=()): ...

# jobs.py
@dataclass
class Job:
    ...
    rotations: tuple = ()    # 与 photos 等长（或更短），条目 ∈ {0,90,180,270}

def build_job(st, photos, sheet_key, cell_key, *, ...,
              offset_pct=(0.0, 0.0), borderless_active=False,
              rotations=()) -> Job: ...
```

- `Job.render` 把 `self.rotations` 原样透传给 `render_page`；编排层不做任何
  角度换算或几何决策（全局约束：jobs 层禁几何）。
- `cli.py` 不传 `rotations`，默认 `()` 与现行为逐像素等价——现有渲染测试与
  `_lab/m1m2_check.py`、`_lab/check_gui_cli_parity.py` 必须不受影响。
- `rotations` 用 tuple 落库（`Job` 是 dataclass，防可变默认值共享）。

## 4. 界面

照片列表下方按钮行从 `[添加照片…] [清空]` 变为 `[添加照片…] [清空] [旋转 90°]`。

- 点击取 `photo_list.currentRow()`：
  - 无选中（-1 或越界）→ 状态栏提示"请先选中照片"，**不算错误**（不标红、
    沿用现有 `_set_status` 正常色），不动任何数据；
  - 有选中 → `photo_rotations[row] = (photo_rotations[row] + 90) % 360`，
    刷新该行列表文字，然后 `self._debounce.start()`（与添加/清空同路径）。
- 列表项文字：有旋转时追加后缀 `↻90°`（0° 不显示后缀，保持现有文字逐字不变，
  免得动掉既有断言列表文案的测试）。文字重编码抽成 `_photo_item_text(name,
  img_or_None, angle)` 单一函数，`append_photo` 与旋转刷新共用，杜绝两处漂移。
- 读取失败的占位项（`photos[i] is None`）也允许旋转与记角度（数据上不坏，
  渲染时被跳过），行为不做特殊分支。
- `photo_rotations` 与 `photos` 严格等长同序：`append_photo` 追加 0，
  `_on_clear_photos` 清空。

## 5. 持久化

`last_job` 新增 `rotations`：`list[int]`，与 `photo_paths` 按下标一一对应。

- `save_last_job` 写 `list(self.photo_rotations)`。
- `_restore_last_job`：`rotations` 必须是 list/tuple 且每项 `int(...)` 可转，
  否则**整体不恢复**（全 0）；长度与恢复的照片数不符时截断/补 0——逐项降级
  会让"第 3 张转了 90°"错位成"第 4 张转了"，比全不恢复更糟。恢复路径沿用
  `_safe` 口径，坏配置不报错不闪退。
- 恢复顺序：先 `append_photo(p)` 再按下标套角度（现有实现是逐条 append，角度
  在全部 append 完成后一次性写入 `photo_rotations`，避免中途 `_refresh` 读到
  半截状态——`_restore_last_job` 本来就在 `__init__` 里、`_refresh` 之前跑完）。

## 6. 错误处理

| 场景 | 处理 |
|---|---|
| 未选中就点旋转 | 状态栏正常色提示"请先选中照片"，不标红 |
| `rotations` 含非法角度 | 归一后仍非法按 0 处理，不抛错 |
| `last_job.rotations` 形状坏 | 整体不恢复（全 0），其余字段照常 |
| 旋转后排版失败 | 与现有参数变更同路径：状态栏红字，导出禁用（旋转不改排版，理论上不会新增此分支，但不得假设） |

## 7. 测试方案

全部脱机（`offscreen`），进 `tests/`：

- `test_render_rotations.py`：
  - **I-1 逐像素对拍**：横图 90/180/270 三档，"渲染时转" vs "预转好再渲"；
  - fit 模式下横图转 90° 后画面高度显著增大（用 `Placement.dest_mm` 断言，
    不复刻几何公式）；
  - `rotations=()` 与全 0 逐像素相同（回归保护 CLI 不受影响）；
  - 角度归一：-90 归一为 270 正常生效；45 / 字符串 / None 降级为 0 不抛错；
  - 旋转格（`cell.rotated`）与照片旋转叠加不崩、偏移换算仍走 `rotate_offset`。
- `test_jobs_rotations.py`：`build_job` 透传 `rotations` 到 `Job`，
  `Job.render` 透传到 `render_page`（编排层不得自己换算）。
- `test_app_smoke.py` 增补：
  - 点按钮后 `photo_rotations` 变化、列表文字出现 `↻90°` 后缀；
  - 未选中点击不改数据、不动预览；
  - 清空重置 `photo_rotations`；
  - `save_last_job` → 新窗口恢复后角度与照片下标对齐；
  - 坏 `rotations` 配置（长度不符、含字符串）按第 5 节口径降级。
- `test_cli_frozen`（既有）与 `_lab` 两个比对脚本必须不改仍绿。

## 8. 验收标准

1. `python -m pytest tests/ -q` 全绿（现有 + 新增）。
2. `python _lab/m1m2_check.py` 仍全 OK、exit 0。
3. `python _lab/check_gui_cli_parity.py` 仍 OK（CLI 无旋转路径不受影响）。
4. 手工核对（用户场景复现）：加载截图中的横图，A4 + 3R + 完整放入，选中照片
   点「旋转 90°」，预览画面占格高度明显增大；导出 PDF 与预览一致。

## 9. 遗留与后续

- 逆时针 / 任意角度 / 多选批量：待真实需求出现再立增量。
- 旋转参与装箱（横图自动配横格）：即被否决的方案 C，若将来要做，必须先重开
  "证件照格不得旋转"的全局约束评审，不在本增量里预埋开关。
