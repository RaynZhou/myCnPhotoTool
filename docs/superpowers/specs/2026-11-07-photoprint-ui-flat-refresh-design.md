# 界面重做：极简扁平风（2026-11-07）

本文件是 **gui-exe 设计 §3「控件规则」的补丁**：只动界面结构与外观，不动排版
几何、渲染、打印路径与持久化字段。风格基准为 StyleKit「极简扁平 (Minimalist
Flat)」——白底、单一强调色、1px 细线分区、无阴影、无渐变、无纹理。

## 1. 用户裁决

1. **结构也重排**：左侧卡片式参数栏 + 右侧预览卡片 + 底部操作条（不是只换配色）。
2. **仅浅色主题**：不做深色切换，避免两套样式与一个状态枚举。

## 2. 设计令牌（`photoprint/app/theme.py` 是唯一出处）

| 类别 | 令牌 | 值 |
|---|---|---|
| 底色 | `BG` | `#F5F6F8` |
| 卡片 | `SURFACE` | `#FFFFFF` |
| 细线 | `LINE` / `LINE_STRONG` | `#E5E7EB` / `#D6DAE0` |
| 文字 | `TEXT` / `TEXT_MUTED` | `#1F2329` / `#6B7280` |
| 强调色 | `ACCENT` / `_HOVER` / `_PRESSED` / `_SOFT` | `#2563EB` / `#1D4ED8` / `#1E40AF` / `#EAF1FE` |
| 预览画布 | `CANVAS` | `#EDEFF3` |
| 错误红 | `DANGER` | `#B00000`（与 `ERROR_COLOR` 同值） |
| 字体 | `FONT_FAMILY` | 微软雅黑 UI，基准 9pt |
| 圆角 | 控件 / 卡片 | 6px / 10px |
| 间距 | 页边距 / 卡片内边距 / 行距 / 卡片间距 | 16 / 14 / 10 / 12 |

样式以 Python 字符串 `APP_QSS` 承载，**不引入 `.qss`/`.qrc` 资源文件**：
onefile exe 不需要往 `PhotoPrint.spec` 加 `datas` 就能完整生效。

唯一进包的外部资源是品牌图标（2026-11-07 追加）：`assets/logo.png`（512，窗口与标题栏
左上角）与 `assets/logo.ico`（16–256 多尺寸，exe 图标），同源自一盘蓝底白打印机的
圆角磁贴，主色锁 `ACCENT`。装配集中在 `photoprint/app/branding.py`：`app_icon()` /
`logo_pixmap(size)` 在资源缺失时返回空 `QIcon`/`QPixmap`，**不抛异常**；打包由
`build_exe.ps1` 的 `--icon` 与 `--add-data "assets;photoprint/app/assets"` 负责，
开发态与 onefile 解包态都靠 `Path(__file__).parent / "assets"` 命中。

基础风格切到 `Fusion`（`install_app_style()`，异常吞掉）：Windows 原生主题下
combo / check 的子控件由系统绘制，QSS 只生效一半，圆角与指示器会不一致。

## 3. 布局线框

```
左区 (QScrollArea#Sidebar, 固定 748px, 右侧 1px 细线)
├─ 品牌头：Logo 34px + AppTitle「相片打印助手」+ Hint「3R / 自定义尺寸 · 拼版直打」
├─ 并排列 (QHBoxLayout, 间距 12)
│  ├─ 左列 Card「照片」(宽 344)  缩略图网格 2 列 (最小高 220) + 两行按钮 (添加/导入、旋转/清空)
│  └─ 右列 (宽 360)
│     ├─ Card「纸张与布局」 纸张 · 格子 · 模式 · 边距 · 输出 dpi｜打印质量 · 介质类型
│     └─ Card「文字叠加」 日期标签 / 文字水印 两组字段网格 + 应用到所有照片
右区
├─ 预览头：CardTitle「预览」+ 页码「第 i / N 页」+ 上一页 / 下一页
├─ Card#PreviewCard (底色 CANVAS)：PreviewView
└─ ActionBar：驱动页开关 · 打印机 · 导出 PDF（次要）· 打印…（主按钮, 强调色实心)
```

- 预览格线 `LINE_STRONG` 1px；当前格 `ACCENT` 2px（原 3px 过重）。
- 白纸靠 `CANVAS` 灰底衬托而不是阴影——扁平风里“纸浮在台面上”不用投影。
- 文字叠加字段用「左标签 + 右控件」两列网格（`theme.field_grid`），比原来一
  行塞 6~7 个控件更易读，也让侧栏少一半高度。

### 3.1 两列左区与开窗尺寸（2026-11-07 追加）

用户反馈「默认打开看不全」「标签没对齐」「左栏可以放宽」后的三条硬约束：

| 约束 | 做法 |
|---|---|
| 三张卡片一屏看全 | 照片列与设置列并排，左区宽 = `2*PAGE_MARGIN + PHOTO_COL_W + COL_GAP + PANEL_COL_W` = 16×2+344+12+360 = **748**；单列堆叠要 1200px 以上，必滚 |
| 左区内层不得宽于外框 | `LEFT_W` 必须把两侧 `PAGE_MARGIN` 算进去，否则内层比外框宽、右下角被裁——这正是第一版“看不全”的直接原因 |
| 字段名对齐 | 标签固定宽（`LABEL_W`=62 / `LABEL_W_SMALL`=46）+ `Qt.AlignLeft`，同卡片同列标签同宽同左沿，控件左边线因此共线；旧版右对齐时左沿参差 |
| 开窗尺寸随屏幕 | `initial_window_size(screen)`：默认 1400×960，小屏按可用区各留 40/60 边距收，下限 `MIN_WIN_W`=1140 / `MIN_WIN_H`=700（再小会把操作条与状态栏推出屏幕） |
| 缩略图两列 | IconMode 每格 = 图标 120 + QSS 内边距 12 + 描边 2 + 委托边距 ≈ **140px**，两列要视口 ≥**283px**，而视口 ≈ 列宽 − 40 → `PHOTO_COL_W` 取 **344**（304 视口，留 24px 余量）。324 时只差几像素就全退成一列，卡片右侧空一大块；`setGridSize` 也救不回来（148×2 > 284 反而更糟） |
| 文件名不被裁 | 每项自己 `setSizeHint(140 × (120 + 2×行高 + 16))`。**不能信委托的 `sizeHint`**：窗口级 QSS 下它只按「一行文字」报高（139px < 图标 120 + 两行 30），靠它就会裁掉尺寸行；若再让文字 `wordWrap=True`，折出的第三行还会溢出格子、被下一行图标压住。因此文字不换行、自己按可用像素做 `ElideMiddle`（保留 `.jpg`），完整名进 `setToolTip` |

「纸张与布局」改为 6 行 `QGridLayout`（`theme.grid_cell`）：纸张 / 格子 / 模式 /
边距各占整行（`span=3`），输出 dpi 与打印质量并排一行，介质类型整行收尾——
比原来每行一组上下叠放少 3 行高度。长选项名（如「铺满可打印区（留白边）」）
在 360px 的列宽里不截断，这也是设置列不跟照片列挤在一起的原因。

## 4. 不可改动清单（现有测试钉住的接口）

| 约束 | 出处 |
|---|---|
| `statusBar().styleSheet()` 正常态为 `""`、错误态含 `color:#b00000` | `test_app_print_media` |
| `photo_list.styleSheet()` 含 `::item:selected`（选中样式仍内联在列表自身） | `test_placement` |
| `ERROR_COLOR == "#b00000"`；`rotate_btn` / `import_btn` / `print_btn` / `printer_box` objectName | 多处 |
| `overlay_group.isEnabled()/toolTip()` 语义（无蓝框 → 整组置灰 + 提示） | `test_app_main_window` |
| 照片网格仍是 IconMode + Wrapping + Static + `GALLERY_THUMB_PX`，且窗口 1400×1000 时 `height() > 150`、宽度 < 窗口一半 | `test_app_main_window` |
| 状态栏文案逐字不变（含“未打印：缺纸”“已取消”等精确相等断言） | `test_app_print_media` |

主按钮靠 `objectName="print_btn"` 命中 `QPushButton#print_btn` 规则，因此不必
改 objectName 也能拿到强调色实心样式。

## 5. 验收

- `python -m pytest -q` 全绿（含 `tests/test_app_theme.py`：窗口样式与 `theme.APP_QSS`
  同源、页码跟随页数、预览配色取自主题令牌、色块用 `swatch_style`；含
  `tests/test_app_layout.py`：左区一次看全不滚、两列并排、字段名同宽同左沿、
  开窗尺寸随屏收敛、logo 资源确实装配到窗口；含 `test_gallery_cell_fits_two_text_lines`
  与 `test_long_photo_name_is_elided_one_line`：格子容得下两行字、长名字只占一行且带悬停全名）。
- **进程退出码也必须是 0**：界面用例收尾要 `close` + `deleteLater`（`tests/conftest.py`
  的 `_reap_qt_windows`）。窗口引用环被循环 GC 拖到 `QApplication` 析构之后才回收时，
  pytest 已经打印「passed」，进程却以 0xC0000409 / 0xC0000005 退出，CI 判失败。
- `python -m photoprint.app` 目检：三张卡片一屏看全、字段名成列、左上角有 logo、
  照片选中态明显、每张缩略图下的「文件名 + 像素尺寸」两行完整不被裁、白纸浮于
  浅灰画布、打印为主按钮、错误态红字。
- `.\build_exe.ps1` 产出的 exe 外观一致，且 exe 图标就是 `assets/logo.ico`
  （构建脚本传 `--icon` 与 `--add-data`）。
