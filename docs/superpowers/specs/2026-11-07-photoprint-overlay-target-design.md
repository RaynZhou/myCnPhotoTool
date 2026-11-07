# 文字叠加的作用对象 + 删除裁切微调与「清空格」（2026-11-07）

本文件是 **gui-exe 设计 §3「控件规则」与 11-06 文字叠加两份设计的补丁**，只改
三处交互与一份数据契约，不动几何、不动打印路径。

## 1. 用户裁决（逐条对应需求原文）

1. **删除「水平微调 / 垂直微调」**——彻底删：面板控件、`Job.offset_pct`、
   `render_page(offset_pct=…)`、`crop.rotate_offset`、对应测试。
2. **「应用到所有照片」按钮 → 勾选框「文字叠加效果应用到所有照片」**，且
   **文字叠加默认只对预览里蓝框那张照片生效**。
3. **删除「清空格」按钮**（用户：基本没用到）。清格仍由预览右键「移除该照片」负责。

范围默认值：勾选框只覆盖**当前预览页**（不跨页）；无蓝框时整组置灰并提示。

## 2. 为什么原来的「应用到所有照片」看着像没作用

旧模型里 `date_enabled` / `wm_enabled` 是**全局开关**：勾上就等于所有格都加字，
那个按钮只额外把「角标 + 旋转」补写一遍，用户看不出差别。所以这次不是把按钮换个
样子，而是把**开关语义本身改成逐张**：

| | 旧 | 新 |
|---|---|---|
| 开关粒度 | 全局（每格都加） | 每张照片一个 `date_on` / `wm_on` |
| 编辑对象 | 照片列表选中的那张（或全局默认） | 预览蓝框那一格所放的照片 |
| 批量 | 按钮补写角标（开关仍是全局） | 勾选框把「值 + 开关」套到本页全部已放照片 |
| `TextSpec.enabled` | 直接用复选框 | 由库里逐张开关派生（`any(…)`） |

派生这一步是必须的：选中照片 A（勾着）→ 点照片 B（没勾）时复选框会变成未勾，
若仍拿它当全局开关，A 的字会跟着消失。

## 3. 数据与渲染

- `Job.date_cells` / `Job.wm_cells`：**逐格** bool，长度 = `页数 × 每页格数`，
  `Job.render` 按页切片再传下去。
- `render_page(..., date_cells=(), wm_cells=())`：`_cell_on(flags, idx)` 门控，
  **空＝全部生效**（CLI 与旧调用方不传，行为逐像素不变）。
- 界面永远传全长列表（全 False 也是列表），因此「一张都没勾」不会退化成「全加」。
- `pool[i]["date_on"] / ["wm_on"]` 是界面层的真相，物化到 `*_cells` 只发生在
  `_rebuild_job` 里的一次循环（与 `date_overrides` 同一个循环，同一套下标规则）。

## 4. 持久化

`last_job` 新增 `pool_on: [[date_on, wm_on], …]` 与 `ov_apply_all: bool`；
删除 `offset_pct`。恢复时：

- 有 `pool_on` → 逐张照读（长度不足的补旧全局值）。
- 无 `pool_on`（旧配置）→ 整库按旧的 `date_overlay.enabled` /
  `watermark_overlay.enabled` 铺开，与升级前逐像素一致。
- `date_overlay.enabled` 现在按 `any(date_on)` 写盘：旧版本读它仍能判断“有没有加字”。

## 5. 被推翻/删除的用例

- `tests/test_crop_offset.py`（`rotate_offset` 轴与符号）——函数已删。
- `tests/test_render_offset.py`（偏移改变渲染像素）——参数已删。
- `tests/test_jobs.py`：`test_offset_changes_rendered_pixels`、
  `test_build_job_passes_percentage_through_without_converting`。
- `tests/test_app_main_window.py`：两条 offset 配置降级、`test_offset_sliders_reach_jobs`、
  `test_select_photo_loads_its_overlay` / `test_deselect_restores_base` /
  `test_apply_overlay_to_all`（语义变了，按新模型重写）。
- `tests/test_placement.py::test_clear_cell_button_exists_and_clears` → 改为断言
  按钮**不存在**、`clear_cell()` 仍生效。

新护栏（都做过变异验牙，`MUTATION-TEMP` 已清零）：

- `test_date_cells_gate_each_cell` / `test_wm_cells_gate_is_independent_from_date`
  —— `_cell_on` 恒真时两条转红。
- `test_date_cells_gate_which_cells_get_overlay` / `test_cell_flags_are_sliced_per_page`
  —— 编排层切片与门控。
- `test_no_blue_frame_disables_overlay_panel` / `test_apply_all_checkbox_covers_current_page`
  / `test_apply_all_does_not_touch_other_pages` —— 把逐张开关写成整库时三条转红。
- `test_rebuild_materializes_date_texts` 钉住 `date_cells` 只有蓝框那格为 True。

## 6. 未覆盖 / 遗留

- 勾选框是**动作＋范围**：勾上即刻套一次，勾着的状态下继续改角标/开关也会同步到
  本页（因为目标集合仍是整页）。它不是持续规则，翻页/新增照片都不自动套。
- 恢复上次设置后没有蓝框（`_current_cell` 不落盘），面板是置灰状态；点一下预览格
  即恢复编辑。若以后要“开机就选中第一张”，需要另行裁决是否改预览默认高亮。
- `crop.cell_crop_box` 的 `zoom` / `dx_mm` / `dy_mm` 保留（裁切基元 + 已有边界用例），
  当前渲染路径不再传。
