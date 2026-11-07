"""单窗口表单界面：选图 → 选纸/格/模式 → 预览 → 导出等尺寸 PDF。

本层不含 mm/像素换算与裁切几何（全局约束）：百分比偏移、页码切分、
格子尺寸一律交 jobs/core。异常一律收敛成状态栏文字，不得外抛——
窗口化 exe 没有控制台，抛出去就是静默闪退。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QSize, QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListView,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from photoprint import jobs
from photoprint.app import view, worker
from photoprint.app.preview_view import PreviewView
from photoprint.core import modes, render, specs, store
from photoprint.core.text_overlay import Corner, TextSpec
from photoprint.win import media as media_mod

MODE_LABELS = (
    ("自动", None),
    ("完整放入（留白）", modes.FIT_TO_PRINTABLE),
    ("铺满可打印区（留白边）", modes.FILL_PRINTABLE),
    ("出血拼版（需人工裁切）", modes.BLEED_TRIM),
)
DPI_CHOICES = ((150.0, "150"), (300.0, "300"), (600.0, "600"))
# 质量只给两档：驱动默认（不写字段）与本机唯一可用的更高档 DMRES_HIGH
# （spec 2026-11-07 §0.2：-1/-2 被夹回 -2，正值被夹回 -3）。
QUALITY_CHOICES = (("驱动默认", None), ("高", media_mod.QUALITY_HIGH))
MEDIA_DEFAULT_LABEL = "驱动默认"
DEBOUNCE_MS = 250
OFFSET_MAX_PCT = 50
GALLERY_THUMB_PX = 120
IMAGE_FILTER = "图片 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp)"
ERROR_COLOR = "#b00000"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")
FONT_CHOICES = (("微软雅黑", "yahei"), ("黑体", "heiti"), ("宋体", "songti"),
                ("Arial", "arial"))
WEIGHT_CHOICES = (("常规", "normal"), ("加粗", "bold"))
CORNER_CHOICES = (("左上", Corner.TL), ("右上", Corner.TR),
                  ("左下", Corner.BL), ("右下", Corner.BR))
ROTATION_LABELS = (("0°", 0), ("45°", 45), ("90°", 90), ("135°", 135),
                   ("180°", 180), ("225°", 225), ("270°", 270), ("315°", 315))
OVERLAY_DEFAULT_RGB = (255, 255, 255)


def list_folder_images(dir_path):
    """顶层、按 IMAGE_EXTS（大小写不敏感）筛选、按路径小写排序的图片路径。

    目录不存在/不可读一律返回 []——窗口化 exe 无控制台，异常外抛即静默闪退。
    仅取文件、不递归子目录（增量①明确排除递归）。
    """
    try:
        entries = list(Path(dir_path).iterdir())
    except (OSError, ValueError):
        return []
    imgs = [str(p) for p in entries
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return sorted(imgs, key=lambda s: s.lower())


def _spin(lo, hi, value=0.0):
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(1)
    box.setSingleStep(0.5)
    box.setValue(value)
    return box


def _slider_row(slider, label):
    row = QHBoxLayout()
    row.addWidget(slider, 1)
    row.addWidget(label)
    return row


def _connect_param_changed(widget, handler):
    """各控件的“值变了”信号名不同，这里统一接到 handler。

    带 `*_` 是因为 valueChanged 会传值、currentIndexChanged 也传值，
    而 handler（QTimer.start）不接受参数。
    """
    for name in ("valueChanged", "currentIndexChanged"):
        sig = getattr(widget, name, None)
        if sig is not None:
            sig.connect(lambda *_: handler())
            return
    raise TypeError(f"控件没有可用的值变更信号：{type(widget).__name__}")


class MainWindow(QMainWindow):
    def __init__(self, st=None, printer_api=None):
        super().__init__()
        if printer_api is None:
            from photoprint.win.api import RealWinApi
            printer_api = RealWinApi()
        self.api = printer_api
        self.st = st if st is not None else store.Store()
        self.st.load()
        self.pool = []             # 库：[{"path": str, "img": PIL|None}]
        self.placements = {}       # 槽位下标 → 库下标；缺省即空格
        self.cell_rot = {}         # 槽位下标 → 0/90/180/270（缺省 0）
        self._pages = 1            # 当前总页数（派生 + 翻页增页）
        self.page_index = 0
        self._current_cell = None  # 预览选中的全局槽位
        self._place_source = None  # 当前作为放置源的库下标（None=无选中，点格纯选中）
        self._ov_base = None       # 全局默认（未选中时面板编辑它），_build_ui 后初始化
        self._ov_editing = None    # 当前编辑的 pool 下标（None＝编辑默认）
        self._ov_loading = False   # 载入照片值时阻断回写
        self._count_last = None    # 上次每页格数（检测结构性布局变更）
        self.job = None
        self._thread = None
        self._task = None
        self._gen = 0
        self._stale = []        # wait 超时没停干净的旧线程，留住引用防其在跑时被回收
        self.setWindowTitle("相片打印助手")
        self._build_ui()
        self._ov_base = self._read_overlay_widgets()
        self._load_printers()
        # 介质下拉跟随打印机：先建连再手工填一次，避免初始化时重复枚举
        self.printer_box.currentIndexChanged.connect(self._load_media_options)
        self._load_media_options()
        # debounce 必须先于恢复设置建好： setCurrentIndex 一类调用会打到信号
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._refresh)
        for w in (self.sheet_box, self.cell_box, self.mode_box, self.gap_box,
                  self.bleed_box, self.dpi_box, self.h_slider, self.v_slider):
            _connect_param_changed(w, self._debounce.start)
        for w in (self.date_font, self.date_size, self.date_weight,
                  self.wm_font, self.wm_size,
                  self.wm_weight, self.wm_alpha):
            _connect_param_changed(w, self._debounce.start)
        for cb in (self.date_corner, self.date_rot, self.wm_corner, self.wm_rot):
            cb.currentIndexChanged.connect(self._on_overlay_widget_changed)
        for cb in (self.date_enabled, self.wm_enabled):
            cb.toggled.connect(lambda _: self._debounce.start())
        self.wm_text.textChanged.connect(lambda _: self._debounce.start())
        self._restore_last_job()
        self._refresh()

    # ---------- 布局 ----------

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        body = QHBoxLayout()
        outer.addLayout(body, 1)

        panel = QFormLayout()
        body.addLayout(panel)

        self.photo_list = QListWidget()
        self.photo_list.setViewMode(QListView.IconMode)   # 图标在上、文字在下、自动换行
        self.photo_list.setMovement(QListView.Static)     # 格子固定不可拖拽重排
        self.photo_list.setWrapping(True)                 # 随栏宽换行成多列
        self.photo_list.setResizeMode(QListView.Adjust)   # 宽度变化时重排列数
        self.photo_list.setWordWrap(True)                 # 长文件名换行
        self.photo_list.setUniformItemSizes(True)         # 网格整齐 + 大数据性能
        self.photo_list.setIconSize(QSize(GALLERY_THUMB_PX, GALLERY_THUMB_PX))
        self.photo_list.setStyleSheet(
            "QListView::item:selected{background:#bcd4ff;border:2px solid #2b6cb0;}")
        self.photo_list.itemClicked.connect(self._on_photo_clicked)
        panel.addRow("照片", self.photo_list)

        add_btn = QPushButton("添加照片…")
        add_btn.clicked.connect(self._on_add_photos)
        import_btn = QPushButton("导入文件夹…")
        import_btn.setObjectName("import_btn")
        import_btn.clicked.connect(self._on_import_folder)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._on_clear_photos)
        rotate_btn = QPushButton("旋转 90°")
        rotate_btn.setObjectName("rotate_btn")
        rotate_btn.clicked.connect(self._on_rotate)
        self.rotate_btn = rotate_btn
        clear_cell_btn = QPushButton("清空格")
        clear_cell_btn.setObjectName("clear_cell_btn")
        clear_cell_btn.clicked.connect(self._on_clear_cell)
        self.clear_cell_btn = clear_cell_btn
        btns = QHBoxLayout()
        btns.addWidget(add_btn)
        btns.addWidget(import_btn)
        btns.addWidget(clear_btn)
        btns.addWidget(rotate_btn)
        btns.addWidget(clear_cell_btn)
        panel.addRow("", btns)

        # 纸张只列 role=paper；格子列 role=cell 加全部 role=paper（人设计 4.3）
        self.sheet_box = QComboBox()
        for s in specs.PAPER_PRESETS:
            self.sheet_box.addItem(s.label, s.key)
        panel.addRow("纸张", self.sheet_box)

        self.cell_box = QComboBox()
        for s in list(specs.CELL_PRESETS) + list(specs.PAPER_PRESETS):
            self.cell_box.addItem(s.label, s.key)
        # 默认选 3R 而非下拉首项 ID1：spec/Step 5 手工核对都写“默认 A4/3R”，
        # 3R 在 PAPER_PRESETS 里、findData 必命中；max(0, …) 只是防 findData 返回 -1。
        self.cell_box.setCurrentIndex(max(0, self.cell_box.findData("3R")))
        panel.addRow("格子", self.cell_box)

        self.mode_box = QComboBox()
        for label, _value in MODE_LABELS:
            self.mode_box.addItem(label)
        panel.addRow("模式", self.mode_box)

        self.gap_box = _spin(0.0, 50.0)
        panel.addRow("格间距 mm", self.gap_box)
        self.bleed_box = _spin(0.0, 20.0, modes.DEFAULT_BLEED_MM)
        panel.addRow("出血 mm", self.bleed_box)

        self.dpi_box = QComboBox()
        for value, label in DPI_CHOICES:
            self.dpi_box.addItem(label, value)
        self.dpi_box.setCurrentIndex(1)      # 默认 300
        panel.addRow("输出 dpi", self.dpi_box)

        # 介质类型 / 打印质量：默认第 0 项“驱动默认”＝不干预 DEVMODE，
        # 与上一轮行为逐字一致（spec 2026-11-07 决策 1）。
        self.media_box = QComboBox()
        self.media_box.addItem(MEDIA_DEFAULT_LABEL, None)
        panel.addRow("介质类型", self.media_box)
        self.quality_box = QComboBox()
        for label, value in QUALITY_CHOICES:
            self.quality_box.addItem(label, value)
        panel.addRow("打印质量", self.quality_box)
        self._media_options = []       # 驱动给的介质项（枚举失败时为空）

        self.h_slider = QSlider(Qt.Horizontal)
        self.h_slider.setRange(-OFFSET_MAX_PCT, OFFSET_MAX_PCT)
        self.v_slider = QSlider(Qt.Horizontal)
        self.v_slider.setRange(-OFFSET_MAX_PCT, OFFSET_MAX_PCT)
        self.h_label = QLabel("0%")
        self.v_label = QLabel("0%")
        self.h_slider.valueChanged.connect(lambda v: self.h_label.setText(f"{v}%"))
        self.v_slider.valueChanged.connect(lambda v: self.v_label.setText(f"{v}%"))
        panel.addRow("水平微调", _slider_row(self.h_slider, self.h_label))
        panel.addRow("垂直微调", _slider_row(self.v_slider, self.v_label))

        overlay = QGroupBox("文字叠加")
        ovl = QVBoxLayout(overlay)
        self._date_rgb = OVERLAY_DEFAULT_RGB
        self._wm_rgb = OVERLAY_DEFAULT_RGB

        self.date_enabled = QCheckBox("日期标签")
        self.date_font = QComboBox()
        for label, key in FONT_CHOICES:
            self.date_font.addItem(label, key)
        self.date_size = _spin(1.0, 30.0, 4.0)
        self.date_weight = QComboBox()
        for label, key in WEIGHT_CHOICES:
            self.date_weight.addItem(label, key)
        self.date_corner = QComboBox()
        for label, key in CORNER_CHOICES:
            self.date_corner.addItem(label, key)
        self.date_rot = QComboBox()
        for label, deg in ROTATION_LABELS:
            self.date_rot.addItem(label, deg)
        self.date_color_btn = QPushButton()
        self.date_color_btn.clicked.connect(self._pick_date_color)
        drow = QHBoxLayout()
        for widget in (self.date_font, self.date_size, self.date_weight,
                       self.date_corner, self.date_rot, self.date_color_btn):
            drow.addWidget(widget)
        ovl.addWidget(self.date_enabled)
        ovl.addLayout(drow)

        self.wm_enabled = QCheckBox("文字水印")
        self.wm_text = QLineEdit()
        self.wm_font = QComboBox()
        for label, key in FONT_CHOICES:
            self.wm_font.addItem(label, key)
        self.wm_size = _spin(1.0, 30.0, 6.0)
        self.wm_weight = QComboBox()
        for label, key in WEIGHT_CHOICES:
            self.wm_weight.addItem(label, key)
        self.wm_corner = QComboBox()
        for label, key in CORNER_CHOICES:
            self.wm_corner.addItem(label, key)
        self.wm_rot = QComboBox()
        for label, deg in ROTATION_LABELS:
            self.wm_rot.addItem(label, deg)
        self.wm_color_btn = QPushButton()
        self.wm_color_btn.clicked.connect(self._pick_wm_color)
        self.wm_alpha = QSlider(Qt.Horizontal)
        self.wm_alpha.setRange(0, 100)
        self.wm_alpha.setValue(50)
        wrow = QHBoxLayout()
        for widget in (self.wm_font, self.wm_size, self.wm_weight,
                       self.wm_corner, self.wm_rot, self.wm_color_btn, self.wm_alpha):
            wrow.addWidget(widget)
        ovl.addWidget(self.wm_enabled)
        ovl.addWidget(self.wm_text)
        ovl.addLayout(wrow)
        panel.addRow(overlay)

        self.apply_overlay_btn = QPushButton("应用到所有照片")
        self.apply_overlay_btn.clicked.connect(self._apply_overlay_to_all)
        panel.addRow("", self.apply_overlay_btn)

        self._refresh_overlay_btn_colors()

        self.preview = PreviewView()
        self.preview.cellClicked.connect(self._on_cell_clicked)
        self.preview.cellContextMenuRequested.connect(self._on_cell_context_menu)
        body.addWidget(self.preview, 1)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.next_btn = QPushButton("下一页")
        self.prev_btn.clicked.connect(lambda: self._go_page(-1))
        self.next_btn.clicked.connect(lambda: self._go_page(1))
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)
        # 默认直打：面板已把纸张/几何/介质/质量钉进 DEVMODE，点“打印”就该出纸。
        # 只有无边距这类驱动私有开关需要弹窗，才让用户主动勾上。
        self.driver_page_cb = QCheckBox("打印前打开驱动设置页")
        self.driver_page_cb.setToolTip(
            "不勾：直接打印（按面板与驱动当前设置）；\n"
            "勾上：先弹驱动设置页，可改无边距/灰度等驱动私有选项")
        nav.addWidget(self.driver_page_cb)
        self.printer_box = QComboBox()
        self.printer_box.setObjectName("printer_box")
        nav.addWidget(self.printer_box)
        self.print_btn = QPushButton("打印…")
        self.print_btn.setObjectName("print_btn")
        self.print_btn.clicked.connect(self._on_print)
        nav.addWidget(self.print_btn)
        self.export_btn = QPushButton("导出 PDF…")
        self.export_btn.clicked.connect(self._on_export)
        nav.addWidget(self.export_btn)
        outer.addLayout(nav)

        self.statusBar().showMessage("就绪")

    # ---------- 参数与刷新 ----------

    def _params(self):
        return {
            "sheet_key": self.sheet_box.currentData(),
            "cell_key": self.cell_box.currentData(),
            "gap_mm": self.gap_box.value(),
            "bleed_mm": self.bleed_box.value(),
            "mode": MODE_LABELS[self.mode_box.currentIndex()][1],
            "dpi": float(self.dpi_box.currentData()),
            "offset_pct": (float(self.h_slider.value()),
                           float(self.v_slider.value())),
            "date_overlay": TextSpec(
                enabled=self.date_enabled.isChecked(),
                font_key=self.date_font.currentData(),
                size_mm=float(self.date_size.value()),
                weight=self.date_weight.currentData(),
                corner=self.date_corner.currentData(),
                rotation=self.date_rot.currentData(),
                rgb=self._date_rgb, alpha=255),
            "watermark_overlay": TextSpec(
                enabled=self.wm_enabled.isChecked(),
                text=self.wm_text.text(),
                font_key=self.wm_font.currentData(),
                size_mm=float(self.wm_size.value()),
                weight=self.wm_weight.currentData(),
                corner=self.wm_corner.currentData(),
                rotation=self.wm_rot.currentData(),
                rgb=self._wm_rgb,
                alpha=int(round(self.wm_alpha.value() / 100.0 * 255))),
        }

    def _ensure_count(self):
        """不依赖 job 拿当前每页格数：恢复/迁移在首刷前也要用它算页数。"""
        p = self._params()
        try:
            plan, _ = jobs.build_layout(self.st, p["sheet_key"], p["cell_key"],
                                        p["gap_mm"], p["bleed_mm"], p["mode"],
                                        borderless_active=False)
        except ValueError:
            return self._count_last or 0
        self._count_last = plan.count
        return plan.count

    def _has_any_photo(self):
        return any(self.pool[pi]["img"] is not None
                   for pi in self.placements.values() if 0 <= pi < len(self.pool))

    def _reset_placements(self, msg):
        self.placements = {}
        self.cell_rot = {}
        self._pages = 1
        self.page_index = 0
        self._current_cell = None
        self._set_status(msg)                    # 正常色：引导重摆，非错误

    def place(self, slot, pool_idx):
        """唯一写放置入口（与 2b 拖放共用；迁移重放也走它）。"""
        if not 0 <= pool_idx < len(self.pool):
            return False
        count = self._count_last or 0
        if count and slot >= 0:
            self._pages = max(self._pages, slot // count + 1)
        self.placements[slot] = pool_idx
        self._current_cell = slot
        self._debounce.start()
        return True

    def rotate_cell(self, slot):
        if slot is None or slot not in self.placements:
            self._set_status("请先点选版面中已放图的格")
            return
        self.cell_rot[slot] = (self.cell_rot.get(slot, 0) + 90) % 360
        self._debounce.start()

    def clear_cell(self, slot):
        if slot is None:
            self._set_status("请先点选版面中的格")
            return
        self.placements.pop(slot, None)
        self.cell_rot.pop(slot, None)
        self._maybe_shrink_pages()
        self._debounce.start()

    def _maybe_shrink_pages(self):
        count = self._count_last or 0
        if not count:
            return
        while self._pages > 1:
            last_start = (self._pages - 1) * count
            last_filled = any(last_start <= s < self._pages * count
                              for s in self.placements)
            if last_filled or self.page_index == self._pages - 1:
                break
            self._pages -= 1

    def _rebuild_job(self):
        """算 count→派生 photos/rotations→build_job。结构变（count 变）清空放置。

        先 build_layout 只为拿 count 给物化定长；随后 build_job 作唯一权威
        构造（含模式校验、rotations 归一交 core）——两次纯函数同输入同输出。
        """
        p = self._params()
        try:
            plan, _ = jobs.build_layout(self.st, p["sheet_key"], p["cell_key"],
                                        p["gap_mm"], p["bleed_mm"], p["mode"],
                                        borderless_active=False)
        except ValueError as exc:
            self.job = None
            self._set_status(str(exc), error=True)
            self.export_btn.setEnabled(False)
            return
        count = plan.count
        cleared = False
        if count != self._count_last:
            if self._count_last is not None and self.placements:
                self._reset_placements("布局已变，请重新摆放")
                cleared = True
            self._count_last = count
        n = self._pages * count
        photos = [None] * n
        for slot, pi in self.placements.items():
            if 0 <= slot < n and 0 <= pi < len(self.pool):
                photos[slot] = self.pool[pi]["img"]
        rotations = [self.cell_rot.get(i, 0) for i in range(n)]
        date_texts = [None] * n
        for slot, pi in self.placements.items():
            if 0 <= slot < n and 0 <= pi < len(self.pool):
                date_texts[slot] = self.pool[pi].get("date")
        date_over = [None] * n
        wm_over = [None] * n
        for slot, pi in self.placements.items():
            if 0 <= slot < n and 0 <= pi < len(self.pool):
                e = self.pool[pi]
                date_over[slot] = (e.get("date_corner", self._ov_base["date_corner"]),
                                   e.get("date_rot", self._ov_base["date_rot"]))
                wm_over[slot] = (e.get("wm_corner", self._ov_base["wm_corner"]),
                                 e.get("wm_rot", self._ov_base["wm_rot"]))
        try:
            self.job = jobs.build_job(self.st, photos, p["sheet_key"], p["cell_key"],
                                      gap_mm=p["gap_mm"], bleed_mm=p["bleed_mm"],
                                      mode=p["mode"], offset_pct=p["offset_pct"],
                                      rotations=rotations,
                                      date_overlay=p["date_overlay"],
                                      watermark_overlay=p["watermark_overlay"],
                                      date_texts=date_texts,
                                      date_overrides=date_over,
                                      wm_overrides=wm_over)
        except ValueError as exc:
            self.job = None
            self._set_status(str(exc), error=True)
            self.export_btn.setEnabled(False)
            return
        self.page_index = min(self.page_index, self.job.page_count - 1)
        self.export_btn.setEnabled(self._has_any_photo())
        img_wh, rects = render.page_cells_px(self.job.plan, self.job.sheet,
                                              jobs.PREVIEW_DPI)
        self.preview.set_geometry(rects, img_wh)
        self._highlight_current_cell()
        if not cleared:                             # 结构性清空时保留“请重新摆放”引导，不被信息行覆盖
            self._set_status(f"每页 {self.job.count} 格 · 共 {self.job.page_count} 页 · "
                             f"{self.job.note}")

    def _refresh(self):
        """算排版 → 起线程渲当前页。排版失败只报状态栏，不弹不崩。"""
        self._rebuild_job()
        if self.job is not None:
            self._render_async()

    def _render_async(self):
        self._gen += 1
        gen = self._gen
        self._retire_threads()
        job, index = self.job, self.page_index
        self._thread, self._task = worker.start(
            lambda: job.render(index, jobs.PREVIEW_DPI, show_mask=True))
        self._task.succeeded.connect(lambda image, g=gen: self._on_preview(image, g))
        self._task.failed.connect(
            lambda msg, g=gen: self._on_render_failed(msg, g))
        self._thread.start()

    def _retire_threads(self, timeout=2000):
        """quit 打不断正在 run 的渲染，wait 超时就不能丢引用——丢了引用，在跑的
        QThread 被回收就是 0xC0000409；被丢弃线程迟到的回投靠 gen 当过期帧丢弃。
        timeout=None 是无上限等到底（关窗收尾用：渲染有限，值得等，且不留
        _stale——它是实例属性，随窗口析构即释放，那时再丢引用同样会崩）。"""
        threads = self._stale + ([self._thread] if self._thread is not None else [])
        keep = []
        for th in threads:
            if th.isRunning():
                th.quit()
                if timeout is None:
                    th.wait()
                elif not th.wait(timeout):
                    keep.append(th)
        self._stale = keep

    def _on_preview(self, image, gen):
        if gen != self._gen:
            return                       # 被丢弃的慢线程迟到的旧帧，不覆盖当前页
        self.preview.show_image(image)

    def _on_cell_clicked(self, position):
        """统一入口：选库图 + 点格 → 放入；无选中 → 纯选中该格（供旋转/清空格）。"""
        count = self._count_last or (self.job.count if self.job else 0)
        slot = self.page_index * count + position
        row = self._place_source
        if row is not None and 0 <= row < len(self.pool):
            self.place(slot, row)           # 选库图 + 点格 → 放入（与 2b 同入口）
        else:
            self._current_cell = slot       # 无选中 → 纯选中，供旋转/清空格
        self._highlight_current_cell()

    def _on_cell_context_menu(self, position, global_pos):
        """预览格右键：命中已放置的格 → 弹“移除/旋转”菜单，作用于该格全局槽位。"""
        count = self._count_last or (self.job.count if self.job else 0)
        if not count:
            return
        slot = self.page_index * count + position
        if slot not in self.placements:
            return                              # 空格不弹
        menu = QMenu(self)
        act_remove = menu.addAction("移除该照片")
        act_rotate = menu.addAction("旋转 90°")
        chosen = menu.exec(global_pos)
        if chosen is act_remove:
            self.clear_cell(slot)
        elif chosen is act_rotate:
            self.rotate_cell(slot)

    def _on_photo_clicked(self, item):
        """照片列表项点击：首次选中作为放置源；再次点同一张 → 取消。

        QListWidget 无自带反选，靠 currentRow 会残留导致“选一次就停不下来”；
        用 _place_source 作唯一真相，并同步清列表高亮。"""
        row = self.photo_list.row(item)
        if row == self._place_source:
            self._place_source = None
            self.photo_list.clearSelection()
            self.photo_list.setCurrentRow(-1)      # 清当前行（高亮不再停留）
            self._set_status("已取消选中：点版面格将选中格（供旋转/清空格）")
            self._ov_editing = None
            self._load_overlay_widgets_from_base()
        else:
            self._place_source = row
            self.photo_list.setCurrentRow(row)
            self._ov_editing = row
            self._load_overlay_widgets_for(row)

    def _highlight_current_cell(self):
        """当前选中格高亮：仅当选中格落在当前页才映射到页内序。"""
        count = self._count_last or 0
        pos = None
        if self._current_cell is not None and count \
                and self._current_cell // count == self.page_index:
            pos = self._current_cell % count
        self.preview.set_current_cell(pos)

    def _on_clear_cell(self):
        self.clear_cell(self._current_cell)
        self._highlight_current_cell()

    def _on_render_failed(self, msg, gen):
        if gen == self._gen:
            self._set_status(msg, error=True)

    def _go_page(self, delta):
        if self.job is None:
            return
        if delta > 0 and self.page_index >= self._pages - 1:
            self._pages += 1                        # 末页之后追加空页
        nxt = self.page_index + delta
        if 0 <= nxt < self._pages:
            self.page_index = nxt
            self._current_cell = None               # 翻页即弃旧选中
            self._maybe_shrink_pages()              # 离开空末页时收缩
            self._refresh()

    def _pick_date_color(self):
        c = QColorDialog.getColor(QColor(*self._date_rgb), self, "日期颜色")
        if c.isValid():
            self._date_rgb = (c.red(), c.green(), c.blue())
            self._refresh_overlay_btn_colors()
            self._debounce.start()

    def _pick_wm_color(self):
        c = QColorDialog.getColor(QColor(*self._wm_rgb), self, "水印颜色")
        if c.isValid():
            self._wm_rgb = (c.red(), c.green(), c.blue())
            self._refresh_overlay_btn_colors()
            self._debounce.start()

    def _refresh_overlay_btn_colors(self):
        for btn, rgb in ((self.date_color_btn, self._date_rgb),
                         (self.wm_color_btn, self._wm_rgb)):
            btn.setStyleSheet(
                "background:rgb(%d,%d,%d);border:1px solid #888;" % rgb)

    def _read_overlay_widgets(self):
        return {"date_corner": self.date_corner.currentData(),
                "date_rot": self.date_rot.currentData(),
                "wm_corner": self.wm_corner.currentData(),
                "wm_rot": self.wm_rot.currentData()}

    def _load_overlay_widgets_for(self, pi):
        e = self.pool[pi]
        self._ov_loading = True
        try:
            self._select_by_data(self.date_corner, e.get("date_corner", self._ov_base["date_corner"]))
            self._select_by_data(self.date_rot, e.get("date_rot", self._ov_base["date_rot"]))
            self._select_by_data(self.wm_corner, e.get("wm_corner", self._ov_base["wm_corner"]))
            self._select_by_data(self.wm_rot, e.get("wm_rot", self._ov_base["wm_rot"]))
        finally:
            self._ov_loading = False

    def _load_overlay_widgets_from_base(self):
        self._ov_loading = True
        try:
            for key, cb in (("date_corner", self.date_corner), ("date_rot", self.date_rot),
                            ("wm_corner", self.wm_corner), ("wm_rot", self.wm_rot)):
                self._select_by_data(cb, self._ov_base[key])
        finally:
            self._ov_loading = False

    def _on_overlay_widget_changed(self, *_):
        if self._ov_loading:
            return
        vals = self._read_overlay_widgets()
        pi = self._ov_editing
        if pi is not None and 0 <= pi < len(self.pool):
            self.pool[pi].update(vals)
        else:
            self._ov_base.update(vals)
        self._debounce.start()

    def _apply_overlay_to_all(self):
        vals = self._read_overlay_widgets()
        self._ov_base.update(vals)
        for e in self.pool:
            e.update(vals)
        self._rebuild_job()

    def _set_status(self, text, error=False):
        self.statusBar().setStyleSheet(f"color:{ERROR_COLOR}" if error else "")
        self.statusBar().showMessage(text)

    # ---------- 照片 ----------

    def _on_add_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择照片",
                                                self._start_dir(), IMAGE_FILTER)
        for p in paths:
            self.append_photo(p)
        self._debounce.start()

    def _on_import_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择照片文件夹",
                                             self._start_dir())
        if not d:
            return                      # 取消：零副作用
        self.import_folder(d)

    def import_folder(self, dir_path):
        """把 dir_path 顶层图片按名排序逐张 append_photo，末尾单次 debounce。

        复用 append_photo 的读图/标红容错：坏图不阻塞其余。空目录/无图不动列表、
        不起 debounce，只给正常色提示（与“请先选中照片”同档）。返回识别张数。
        """
        paths = list_folder_images(dir_path)
        if not paths:
            self._set_status("该文件夹没有可导入的图片")
            return 0
        for p in paths:
            self.append_photo(p)
        self._debounce.start()
        self._set_status(f"已导入 {len(paths)} 张图片")
        return len(paths)

    def append_photo(self, path):
        """读图失败不阻塞其余：img=None 进库，被放置时物化成空格；列表标红。"""
        name = Path(path).name
        try:
            img = jobs.load_photo(path)
        except Exception as exc:      # IO 边界什么都可能抛，全部收敛
            self.pool.append({"path": str(path), "img": None, "date": None,
                              "date_corner": self._ov_base["date_corner"],
                              "date_rot": self._ov_base["date_rot"],
                              "wm_corner": self._ov_base["wm_corner"],
                              "wm_rot": self._ov_base["wm_rot"]})
            item = QListWidgetItem(self._photo_item_text(name, None))
            item.setForeground(QColor(ERROR_COLOR))
            self.photo_list.addItem(item)
            self._set_status(f"无法读取 {name}：{exc}", error=True)
            return
        self.pool.append({"path": str(path), "img": img,
                          "date": jobs.photo_date_text(path),
                          "date_corner": self._ov_base["date_corner"],
                          "date_rot": self._ov_base["date_rot"],
                          "wm_corner": self._ov_base["wm_corner"],
                          "wm_rot": self._ov_base["wm_rot"]})
        item = QListWidgetItem(self._photo_item_text(name, img))
        item.setIcon(QIcon(view.to_thumbnail(img, GALLERY_THUMB_PX)))
        self.photo_list.addItem(item)

    @staticmethod
    def _photo_item_text(name, img):
        """网格项文字两行：文件名 / 尺寸（或读取失败）。旋转在格上，不在此体现。"""
        if img is None:
            return f"{name}\n读取失败"
        return f"{name}\n{img.width}×{img.height}px"

    def _on_rotate(self):
        self.rotate_cell(self._current_cell)

    def _on_clear_photos(self):
        self.pool = []
        self.placements = {}
        self.cell_rot = {}
        self._pages = 1
        self.page_index = 0
        self._current_cell = None
        self._place_source = None
        self._ov_editing = None
        self._load_overlay_widgets_from_base()
        self.photo_list.clear()
        self._refresh()

    # ---------- 导出 ----------

    def export_to(self, out_path):
        """导出等尺寸 PDF。测试直接调它，不经文件对话框。"""
        from photoprint.win import pdf_export

        # 先把待防抖的控件值落成 job：self.job 是上次 _refresh 的快照，而下面
        # 的校验与 dpi 取的是实时值，不先同步就会拿陈旧 job 配新参数导出。
        # 走 _rebuild_job 而非 _refresh：导出不需重渲预览，不起那条会被丢弃的线程。
        self._debounce.stop()
        self._rebuild_job()
        if self.job is None or not self._has_any_photo():
            raise ValueError("没有可导出的照片")
        pages = jobs.render_all(self.job, self._params()["dpi"], show_mask=False)
        pdf_export.export_pdf(pages, self.job.sheet, out_path)
        self.save_last_job(out_dir=str(Path(out_path).parent))
        return Path(out_path)

    def _on_export(self):
        suggested = str(Path(self._start_dir()) / "photoprint.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", suggested,
                                             "PDF (*.pdf)")
        if not path:
            return
        try:
            got = self.export_to(path)
        except Exception as exc:      # 无权限/磁盘满/img2pdf 异常
            self._set_status(f"导出失败：{exc}", error=True)
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self._set_status(f"已导出 {got.name}（打印时请选“实际大小/100%”）")

    # ---------- 打印 ----------

    def _load_printers(self):
        """填充打印机下拉。win32 异常（无后台打印程序/未装 pywin32）→ 留空、
        禁用、不崩——窗口化 exe 无控制台，抛出去即静默闪退。
        默认选中系统默认打印机（§4）；取不到/不在列表则回退第一项。"""
        self.printer_box.clear()
        try:
            names = list(self.api.enum_printers())
        except Exception:
            names = []
        for n in names:
            self.printer_box.addItem(n)
        self.printer_box.setEnabled(bool(names))
        if not names:
            return
        try:
            default = self.api.get_default_printer()
        except Exception:
            default = None
        idx = names.index(default) if default in names else 0
        self.printer_box.setCurrentIndex(idx)

    def _load_media_options(self, *_):
        """按当前打印机填充介质下拉。

        第 0 项永远是“驱动默认”（不干预）；其后是驱动给的名字与数值。枚举失败
        （无驱动/无 pywin32）只剩第 0 项，打印照旧可用——介质只是画质增强。
        换打印机时尽量保留原选中值（同一驱动的两台机通常是同一组介质）。
        """
        keep = self.media_box.currentData()
        printer = self.printer_box.currentText()
        self._media_options = (media_mod.enumerate_media(self.api, printer)
                               if printer else [])
        self.media_box.blockSignals(True)
        try:
            self.media_box.clear()
            self.media_box.addItem(MEDIA_DEFAULT_LABEL, None)
            for opt in self._media_options:
                self.media_box.addItem(opt.name, opt.value)
            idx = self.media_box.findData(keep) if keep is not None else 0
            self.media_box.setCurrentIndex(max(0, idx))
        finally:
            self.media_box.blockSignals(False)

    def _on_print(self):
        """直打全部页：先同步落最新 job（含旋转/偏移），打印前实测驱动表单，
        渲染交 render_all（关遮罩，I-2），走 gdi_print.print_pages（默认
        prompt=False 直打；勾了“打印前打开驱动设置页”才交回弹窗路径）。
        异常全兜成状态栏，不外抛。"""
        from photoprint.win import forms as forms_mod
        from photoprint.win import gdi_print

        self._debounce.stop()
        try:
            self._rebuild_job()
        except Exception as exc:
            self._set_status(f"排版失败：{exc}", error=True)
            return
        if self.job is None:
            return                    # _rebuild_job 已把准确原因写进状态栏，不覆盖
        if not self._has_any_photo():
            self._set_status("没有可打印的照片", error=True)
            return
        printer = self.printer_box.currentText()
        if not printer:
            self._set_status("未检测到可用打印机", error=True)
            return
        dpi = self._params()["dpi"]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # 打印前实测驱动表单（只读），命中则打印路径会用驱动自带表单码；
            # 探测失败一律当“没有表单信息”退回旧行为——绝不让打印因此失败。
            # 不做缓存：用户可能在两次打印之间改了驱动里的纸张设置。
            try:
                measured = forms_mod.measure(self.api, printer)
            except Exception:
                measured = []
            images = jobs.render_all(self.job, dpi, show_mask=False)   # I-2
            # 只有真选了介质/质量才把参数传下去：不选时调用形状与上一轮
            # 逐字一致（不塞 media=None）。
            extra = {}
            opt = self.media_box.currentData()
            if opt is not None:
                media = media_mod.find_media(self._media_options, opt)
                if media is not None:
                    extra["media"] = media
            quality = self.quality_box.currentData()
            if quality is not None:
                extra["quality"] = quality
            res = gdi_print.print_pages(self.api, printer, images,
                                        self.job.sheet, dpi,
                                        prompt=self.driver_page_cb.isChecked(),
                                        forms=measured, **extra)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._set_status(f"打印失败：{exc}", error=True)
            return
        QApplication.restoreOverrideCursor()
        if res.get("cancelled"):                    # W-1：驱动页取消，非错误
            self._set_status("已取消")
        elif res["ok"]:
            msg = f"已发送 {res['pages']} 页到 {printer}"
            form = res.get("paper_form")
            if form:                                # 命中驱动表单：明示用的哪张
                msg += f"（{forms_mod.binding_note(forms_mod.PaperForm(**form))}）"
            if res.get("degraded"):                 # W-3：降级仍成功，附提示
                msg += "（未能打开驱动设置页，已用驱动当前介质）"
            note = res.get("media_note")
            if note:                                # 明示送到驱动的介质/质量
                msg += f"（{note}）"
            self._set_status(msg)
        else:
            self._set_status(f"未打印：{res['message']}", error=True)

    # ---------- 上次设置 ----------

    def save_last_job(self, out_dir=None):
        p = self._params()
        self.st.set_last_job({
            "sheet_key": p["sheet_key"], "cell_key": p["cell_key"],
            # 存下拉索引而不是 mode 内部值：“自动”是 None，反序列化时要判空，
            # 索引没有这个歧义
            "mode_index": self.mode_box.currentIndex(),
            "gap_mm": p["gap_mm"], "bleed_mm": p["bleed_mm"], "dpi": p["dpi"],
            "driver_page": self.driver_page_cb.isChecked(),
            "offset_pct": [self.h_slider.value(), self.v_slider.value()],
            "out_dir": out_dir or self._last_out_dir(),
            "pool_paths": [e["path"] for e in self.pool],
            "placements": {str(s): pi for s, pi in self.placements.items()},
            "cell_rot": {str(s): a for s, a in self.cell_rot.items() if a},
            "date_overlay": {"enabled": self.date_enabled.isChecked(),
                             "font_key": self.date_font.currentData(),
                             "size_mm": float(self.date_size.value()),
                             "weight": self.date_weight.currentData(),
                             "corner": self.date_corner.currentData(),
                             "rotation": self.date_rot.currentData(),
                             "rgb": list(self._date_rgb)},
            "watermark_overlay": {"enabled": self.wm_enabled.isChecked(),
                                  "text": self.wm_text.text(),
                                  "font_key": self.wm_font.currentData(),
                                  "size_mm": float(self.wm_size.value()),
                                  "weight": self.wm_weight.currentData(),
                                  "corner": self.wm_corner.currentData(),
                                  "rotation": self.wm_rot.currentData(),
                                  "rgb": list(self._wm_rgb),
                                  "alpha_pct": self.wm_alpha.value()},
            "ov_base": dict(self._ov_base),
            "pool_ov": [[e.get("date_corner"), e.get("date_rot"),
                         e.get("wm_corner"), e.get("wm_rot")] for e in self.pool],
            "pages": self._pages})
        if not self.st.save():
            self._set_status("本次设置未持久化（写入失败）", error=True)

    def _safe(self, fn):
        """坏配置只降级成“这一项不恢复”，绝不让异常出 __init__（全局约束：窗口化 exe
        无控制台，外抛即静默闪退）。与 store 的“单条坏记录不牵连其余”同口径。
        覆盖 TypeError/ValueError/OverflowError——含 int()/float() 转换、以及 setValue
        把超大值喂给 shiboken C int（4 字节）的溢出（±50% 之外的手改配置、超大数、Infinity）。"""
        try:
            fn()
        except (TypeError, ValueError, OverflowError):
            pass

    def _restore_last_job(self):
        job = self.st.get_last_job()
        if not job:
            return
        for key, box in (("sheet_key", self.sheet_box), ("cell_key", self.cell_box)):
            self._safe(lambda b=box, v=job.get(key): self._select_by_data(b, v))
        mode_index = job.get("mode_index")
        if isinstance(mode_index, int) and 0 <= mode_index < self.mode_box.count():
            self._safe(lambda: self.mode_box.setCurrentIndex(mode_index))
        for key, box in (("gap_mm", self.gap_box), ("bleed_mm", self.bleed_box)):
            if isinstance(job.get(key), (int, float)):
                self._safe(lambda b=box, v=job[key]: b.setValue(float(v)))
        if isinstance(job.get("dpi"), (int, float)):
            self._safe(lambda: self._select_by_data(self.dpi_box, float(job["dpi"])))
        if isinstance(job.get("driver_page"), bool):
            self.driver_page_cb.setChecked(job["driver_page"])
        pct = job.get("offset_pct")
        if isinstance(pct, (list, tuple)) and len(pct) == 2:
            self._safe(lambda: self._apply_offset(pct))
        new_shape = ("placements" in job) or ("pool_paths" in job)
        paths = job.get("pool_paths") if new_shape else job.get("photo_paths")
        for pth in (paths if isinstance(paths, (list, tuple)) else []):
            self.append_photo(str(pth))    # 坏图走标红占位、保留库下标对齐
        pool_ov = job.get("pool_ov")
        if isinstance(pool_ov, (list, tuple)):
            for i, ov in enumerate(pool_ov):
                if i < len(self.pool) and isinstance(ov, (list, tuple)) and len(ov) == 4:
                    self._safe(lambda e=self.pool[i], v=ov: e.update({
                        "date_corner": v[0], "date_rot": v[1],
                        "wm_corner": v[2], "wm_rot": v[3]}))
        self._ensure_count()
        if new_shape:
            self._safe(lambda: self._restore_placements(job))
        else:
            self._safe(lambda: self._migrate_sequential(job))
        self._restore_overlay(job.get("date_overlay"), is_date=True)
        self._restore_overlay(job.get("watermark_overlay"), is_date=False)
        saved_base = job.get("ov_base")
        if isinstance(saved_base, dict):
            self._ov_base.update({k: saved_base[k] for k in
                                  ("date_corner", "date_rot", "wm_corner", "wm_rot")
                                  if k in saved_base})
        self._ov_editing = None
        self._load_overlay_widgets_from_base()

    def _restore_overlay(self, d, is_date):
        if not isinstance(d, dict):
            return
        box = self.date_enabled if is_date else self.wm_enabled
        self._safe(lambda: box.setChecked(bool(d.get("enabled", False))))
        for key, cb in (("font_key", self.date_font if is_date else self.wm_font),
                        ("weight", self.date_weight if is_date else self.wm_weight),
                        ("corner", self.date_corner if is_date else self.wm_corner),
                        ("rotation", self.date_rot if is_date else self.wm_rot)):
            v = d.get(key)
            if v is not None:
                self._ov_loading = True                   # 回灌控件不得反向写 _ov_base
                try:
                    self._safe(lambda c=cb, val=v: self._select_by_data(c, val))
                finally:
                    self._ov_loading = False
        size = self.date_size if is_date else self.wm_size
        if isinstance(d.get("size_mm"), (int, float)):
            self._safe(lambda b=size, v=float(d["size_mm"]): b.setValue(v))
        rgb = d.get("rgb")
        if isinstance(rgb, (list, tuple)) and len(rgb) == 3:
            if is_date:
                self._date_rgb = tuple(int(x) for x in rgb)
            else:
                self._wm_rgb = tuple(int(x) for x in rgb)
        if not is_date:
            if isinstance(d.get("text"), str):
                self._safe(lambda: self.wm_text.setText(d["text"]))
            if isinstance(d.get("alpha_pct"), (int, float)):
                self._safe(lambda: self.wm_alpha.setValue(int(d["alpha_pct"])))
        self._safe(self._refresh_overlay_btn_colors)

    def _restore_placements(self, job):
        """新 schema：placements/cell_rot/pages 逐条降级（引用完整性优先）。"""
        pl = job.get("placements")
        if not isinstance(pl, dict):
            return                                    # 放置段整体降级：保库、重摆
        for k, v in pl.items():
            try:
                slot, pi = int(k), int(v)
            except (TypeError, ValueError, OverflowError):
                continue
            if slot >= 0 and 0 <= pi < len(self.pool):
                self.placements[slot] = pi
        rot = job.get("cell_rot")
        if isinstance(rot, dict):
            for k, v in rot.items():
                try:
                    slot, a = int(k), int(v)
                except (TypeError, ValueError, OverflowError):
                    continue
                if slot in self.placements:
                    self.cell_rot[slot] = a
        count = self._count_last or 1
        try:
            self._pages = max(1, int(job.get("pages")))
        except (TypeError, ValueError, OverflowError):
            self._pages = 1
        if self.placements:
            self._pages = max(self._pages, max(self.placements) // count + 1)

    def _migrate_sequential(self, job):
        """旧 last_job（photo_paths+rotations、无 placements）→ 顺序重放：
        槽 i 放库 i，rotations 位置对齐逐格；任一坏角度整体不恢复（全 0），
        超长截到库长、不足补 0——与旧 _restore_rotations 同容错口径。"""
        count = self._count_last or 0
        n = len(self.pool)
        if not count or not n:
            return
        rots = job.get("rotations")
        vals = [0] * n
        if isinstance(rots, (list, tuple)):
            try:
                parsed = [int(v) for v in rots]
            except (TypeError, ValueError, OverflowError):
                parsed = None
            if parsed is not None:
                parsed = parsed[:n]
                vals = parsed + [0] * (n - len(parsed))
        for i in range(n):
            self.placements[i] = i
            if vals[i] % 360:
                self.cell_rot[i] = vals[i]
        self._pages = max(1, -(-n // count))

    def _select_by_data(self, box, value):
        idx = box.findData(value)
        if idx >= 0:
            box.setCurrentIndex(idx)

    def _apply_offset(self, pct):
        self.h_slider.setValue(int(pct[0]))
        self.v_slider.setValue(int(pct[1]))

    def _last_out_dir(self):
        d = self.st.get_last_job().get("out_dir")
        if not isinstance(d, str):       # 坏配置（非字符串）不报错：与其余字段同口径降级
            return ""
        try:
            return d if d and Path(d).is_dir() else ""
        except (OSError, ValueError):    # 含空字节等非法路径，Path 会抛，一律当“无”处理
            return ""

    def _start_dir(self):
        return self._last_out_dir() or str(Path.home())

    def closeEvent(self, event):
        self._debounce.stop()      # 关窗后 debounce 若还 fire 会另起线程，绕过收尾
        self.save_last_job()
        self._gen += 1             # 之后任何回投都算过期帧
        self._retire_threads(timeout=None)   # 收尾无上限等到底，不留随窗口析构即失效的 _stale
        super().closeEvent(event)
