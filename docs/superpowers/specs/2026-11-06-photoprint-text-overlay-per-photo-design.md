# 文字叠加逐张调整（位置/旋转）设计

日期：2026-11-06　基线：`master` @ 0afab1f（数字日期标签 + 文字水印全局叠加已合入）

## 0. 背景与决策来源

用户在 exe 实测：当前日期标签与文字水印的**样式是全局统一**的——`_params()` 只组装一份
`date_overlay` / `watermark_overlay` 的 `TextSpec`，`render_page` 对每格套同一份样式；
只有日期**文字**逐张（`pool["date"]`→`date_texts`）。但照片有横版有竖版，同一套位置/
角度放到不同朝向的照片上观感差别大，需要**逐张单独调整**。

与用户逐问确认的决策（本文档不重开这些选择）：

1. **粒度**：逐张照片（与"日期逐张"同口径）。同一照片放到多格样式一致。
2. **编辑交互**：选中库里某张照片（即当前放置源 `_place_source`）→ 面板编辑该张；
   未选中时面板编辑"全局默认模板"。复用现有点击选中，不新增选择控件。
3. **逐张字段**：仅 4 项——日期位置、日期旋转、水印位置、水印旋转。其余
   （开关/字体/字号/粗细/颜色/不透明度/水印文字）保持全局。
4. **旋转**：日期与水印都能旋转，角度取**八档预设** 0/45/90/135/180/225/270/315（顺时针）。
5. **实现路线**：方案 A——全局 base + 逐张生效值直接存进 pool（不做逐字段 None 继承），
   新照片继承入站时的默认，改默认只影响新照片 + "应用到所有照片"按钮。

> **2026-11-07 补丁**：第 2、3、5 条已被推翻——开关改成逐张（`date_on`/`wm_on`）、
> 编辑对象改成预览蓝框那张、“应用到所有照片”按钮换成勾选框且范围＝当前页。
> 现行契约以 `2026-11-07-photoprint-overlay-target-design.md` 为准，本条仅作历史记录。

## 1. 范围与分层不变量

**只动**：`core/text_overlay.py`（`TextSpec.rotation` + `draw_overlay` 旋转分支）、
`core/render.py`（`render_page` 两个新参 + 逐格 `replace`）、`jobs.py`（透传）、
`app/main_window.py`（控件、选中即编辑、物化、持久化）。测试加在
`tests/test_text_overlay.py` / `tests/test_render_overlay.py` / `tests/test_app_main_window.py`。

**分层红线**：几何/旋转全在 `core`；`app` 只汇参数、物化逐张生效值、不做 mm/像素运算；
`jobs` 纯透传（像现有 `date_texts` 一样加参）。

**向后兼容红线**：`render_page`/`Job`/`build_job` 新参一律带默认（`()`＝无覆盖）；
`TextSpec.rotation` 默认 0；`rotation==0` 时 `draw_overlay` 走**现有直绘路径不动** →
默认全 0、无任何逐张覆盖时，导出与升级前逐像素一致。既有全部测试零改动。

## 2. 数据结构

### 2.1 `core/text_overlay.py`
`TextSpec`（frozen dataclass）新增字段：

```python
    rotation: int = 0          # 文字顺时针角度，八档预设之一；0＝不旋转
```

新增模块常量（供 app 下拉与校验共用，core 不强制取值、仅按 int 用）：

```python
ROTATION_PRESETS = (0, 45, 90, 135, 180, 225, 270, 315)
```

### 2.2 `app` pool 条目
`append_photo` 成功入站时，除现有 `path/img/date` 外，种子化 4 个逐张生效字段
（取自当前全局默认 `self._ov_base`）：

```python
pool[i] = {"path", "img", "date",
           "date_corner", "date_rot", "wm_corner", "wm_rot"}
```

失败占位条目（`img=None`）同样带 4 字段（值取默认），保持形状一致。

### 2.3 全局默认模板
`self._ov_base = {"date_corner": Corner.BR, "date_rot": 0,
                  "wm_corner": Corner.BR, "wm_rot": 0}`（初值与现有全局默认角一致）。
面板未选中任何照片时，那 4 个控件编辑的就是它。

## 3. 渲染

### 3.1 `render_page` 新参与逐格生效

签名在 `date_texts=()` 之后加两参：

```python
def render_page(..., date_texts=(), date_overrides=(), wm_overrides=()):
```

循环内叠加段改为：逐格取 override（`(corner, rotation)` 或 None），有则
`dataclasses.replace` 注入到 base spec，再交 `draw_overlay`：

```python
        rect_px = (paste_x, paste_y, piece.width, piece.height)
        if watermark_overlay is not None and watermark_overlay.enabled:
            spec = _with_corner_rot(watermark_overlay,
                                    wm_overrides[idx] if idx < len(wm_overrides) else None)
            text_overlay.draw_overlay(page, rect_px, spec, spec.text, dpi)
        if date_overlay is not None and date_overlay.enabled:
            dt = date_texts[idx] if idx < len(date_texts) else None
            if dt:
                spec = _with_corner_rot(date_overlay,
                                        date_overrides[idx] if idx < len(date_overrides) else None)
                text_overlay.draw_overlay(page, rect_px, spec, dt, dpi)
```

模块级小helper（`render.py` 内，纯函数）：

```python
def _with_corner_rot(spec, ov):
    """ov=(corner, rotation) 或 None。None 原样返回；否则替换 corner/rotation。"""
    if ov is None:
        return spec
    corner, rotation = ov
    return dataclasses.replace(spec, corner=corner, rotation=rotation)
```

`import dataclasses` 加到 render.py 顶部。

### 3.2 `draw_overlay` 旋转分支

**rotation==0**：完全走现有直绘路径（一行不改），保证逐像素等于基线。

**rotation!=0**：把文字画到独立小层再旋转合成，其余（字体/加粗/测量/超长降级/alpha）
沿用现有逻辑。测量后拿到未旋转包围盒 `(tw, th)` 与偏移 `(l, t)`：

```python
    if spec.rotation:
        # 顺时针角度：PIL rotate 逆时针，故取负；expand 让旋转后完整可见
        text_img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(text_img).text((-l, -t), text, font=font, fill=fill,
                                      stroke_width=stroke, stroke_fill=fill)
        rot = text_img.rotate(-int(spec.rotation), expand=True,
                              resample=Image.BICUBIC)
        rw, rh = rot.size
        if rw > avail_w or rh > avail_h:      # 旋转后放不下：降级不画、不抛
            return
        ax, ay = anchor_point(spec.corner, (cw, ch), (rw, rh), inset)
        layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        layer.alpha_composite(rot, (ax, ay))
        region = page.crop((x, y, x + cw, y + ch)).convert("RGBA")
        region = Image.alpha_composite(region, layer)
        page.paste(region.convert("RGB"), (x, y))
        return
```

要点：
- 锚点用**旋转后包围盒** `(rw, rh)` 代入现有 `anchor_point`，四角语义仍成立。
- 逐格隔离沿用现有"整格透明层 + alpha_composite + paste 回页面"，旋转层越界部分被
  `layer` 尺寸裁掉、绝不溢出邻格。
- 超长降级：旋转后包围盒超过 `avail` → 静默不画（与现有降级同口径）。

## 4. jobs 透传

`Job` dataclass 在 `date_texts: tuple = ()` 之后加：

```python
    date_overrides: tuple = ()
    wm_overrides: tuple = ()
```

`Job.render` 里 `dt_chunk` 之后加两切片，并把 `render_page` 调用补两参：

```python
        do_chunk = self.date_overrides[i:i + self.count]
        wo_chunk = self.wm_overrides[i:i + self.count]
        return render.render_page(..., date_texts=dt_chunk,
                                  date_overrides=do_chunk, wm_overrides=wo_chunk)
```

`build_job` 签名加 `date_overrides=(), wm_overrides=()`（`date_texts=()` 之后），
`return Job(...)` 补 `date_overrides=tuple(date_overrides), wm_overrides=tuple(wm_overrides)`。

## 5. app 界面与数据流

### 5.1 控件
面板日期行、水印行各加一个旋转下拉：

```python
ROTATION_LABELS = (("0°", 0), ("45°", 45), ("90°", 90), ("135°", 135),
                   ("180°", 180), ("225°", 225), ("270°", 270), ("315°", 315))
```

`self.date_rot` / `self.wm_rot`：`QComboBox`，`addItem(label, data=int)`，默认索引 0（0°）。
加入 `drow` / `wrow` 布局与防抖连接循环。

### 5.2 选中即编辑（复用 `_place_source`）

新增 `self._ov_editing = None`（当前编辑的 pool 下标或 None）。

`_on_photo_clicked` 末尾联动：
- 选中某张（`_place_source` 设为 row）→ `self._ov_editing = row`；`self._load_overlay_widgets_for(row)`
  把 4 控件载入 `pool[row]` 的生效值；状态提示"正在编辑：{name}（位置/旋转仅此张）"。
- 取消选中（`_place_source`→None）→ `self._ov_editing = None`；`self._load_overlay_widgets_from_base()`
  把 4 控件回填 `self._ov_base`。

4 控件的变更处理（`_on_overlay_corner_rot_changed`，取代直接接 debounce）：
- 载入照片值期间用 `self._ov_loading = True` 阻断回写（防 `setCurrentIndex` 触发写回）。
- 用户真实改动：`self._ov_loading` 为假时——
  - `self._ov_editing is not None` → 写进 `pool[self._ov_editing]` 对应字段；
  - 否则 → 写进 `self._ov_base` 对应字段。
  - 之后 `self._debounce.start()`。

`_params()` 的 base `TextSpec` 仍读面板控件当前值（corner/rotation）作为 base——
逐张差异由 overrides 承载，base 的 corner/rotation 只在"该格无 override"时兜底。

### 5.3 "应用到所有照片"按钮

`self.apply_overlay_btn = QPushButton("应用到所有照片")`，`clicked` →
`_apply_overlay_to_all()`：把 4 控件当前值写进 `self._ov_base`，并逐张覆盖所有
`pool[i]` 的 4 字段，然后 `_rebuild_job()`。

### 5.4 物化 `_rebuild_job`

`rotations`/`date_texts` 之后加两平行元组物化（放置格取该照片生效值，空格 None）：

```python
        date_over = [None] * n
        wm_over = [None] * n
        for slot, pi in self.placements.items():
            if 0 <= slot < n and 0 <= pi < len(self.pool):
                e = self.pool[pi]
                date_over[slot] = (e["date_corner"], e["date_rot"])
                wm_over[slot] = (e["wm_corner"], e["wm_rot"])
```

`build_job(...)` 调用补 `date_overrides=date_over, wm_overrides=wm_over`。

### 5.5 持久化

`save_last_job`：在现有 pool 序列化之外增
- `"ov_base": dict(self._ov_base)`
- `"pool_ov": [[e["date_corner"], e["date_rot"], e["wm_corner"], e["wm_rot"]] for e in self.pool]`

`_restore_last_job`：`append_photo` 逐张入站后，按 `pool_ov`（同序）回填每张 4 字段
（坏形状/越界 `_safe` 降级成默认）；`_ov_base` 用 `ov_base` 回填（缺省保默认）。
`_restore_overlay` 里现有 date/watermark 全局回填保持不变，另回填 4 个逐张相关控件到
`_ov_base`（未选中态即编辑默认）。

## 6. 边界与降级

- 旋转后包围盒超格 → 不画、不抛（§3.2）。
- 字体缺失 / 空文字 / 未启用 → 现有守卫原样静默返回。
- pool 条目缺 4 字段（旧持久化数据）→ 物化/回填用 `.get(key, 默认)` 兜底，不 KeyError。
- 选中照片后被移出/清空：`_ov_editing` 指向的下标失效 → 下一次点击/清空重置为 None，
  `_on_clear_photos` 里连 `self._ov_editing = None` 与控件回填默认一起复位。

## 7. 测试策略与变异

**core `test_text_overlay.py`**：
- `rotation=0` 结果与旧路径逐像素等价（回归红线）。
- 45°/90°：非对称文字 + 目标区像素变化（方向可辨，避免纯色/正方无牙陷阱）。
- 旋转层不溢出邻格：非原点格 + 四周洁净。
- 旋转后超长降级：小格大字号 45° → 不画不抛。

**core `test_render_overlay.py`**：
- 传 `date_overrides`/`wm_overrides` 逐格不同角/角度 → 逐张生效。
- 不传（默认 `()`）→ 逐像素等于基线。
- 某格 override 为 None → 用 base corner/rotation。

**app `test_app_main_window.py`**：
- 选中照片 → 4 控件载入该张值；改 `date_corner` 只写 `pool[pi]`、不动 `_ov_base`、不影响他张。
- 取消选中 → 4 控件回填 `_ov_base`。
- 无选中改 4 控件 → 写 `_ov_base`、不改已有照片。
- "应用到所有照片" → 所有 `pool[i]` 4 字段被覆盖。
- 新 `append_photo` 种子 = 当前 `_ov_base`。
- `_rebuild_job` 物化出正确 `date_overrides`/`wm_overrides`（放置格有值、空格 None）。
- 持久化 roundtrip：两张不同 corner/rot → save → 新窗口逐张回填一致。

**变异验牙**（每项至少一牙）：`_with_corner_rot` 忽略 rotation → 旋转测试红；
overrides 全当 None（不逐张）→ 逐张生效测试红；回写目标分流写反（选中却写 base）→
对应 app 测试红；"应用到所有"漏循环 → 该测试红；种子漏用 `_ov_base` → 继承测试红。

## 8. 验收（exe 手测）

① 点一张竖图→改其日期位置/水印旋转，只有它变、别的不动；② 点另一张横图→各调各的；
③ 不点任何照片时改位置/旋转＝设默认，新加图继承；④ "应用到所有照片"一键统一；
⑤ 斜向水印（45°/135°）观感正确、不溢出邻格；⑥ 重启后每张位置/旋转回填正确；
⑦ 全默认（无单独改、旋转都 0）时导出与升级前逐像素一致。
