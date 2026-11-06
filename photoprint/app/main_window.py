"""单窗口表单界面：选图 → 选纸/格/模式 → 预览 → 导出等尺寸 PDF。

本层不含 mm/像素换算与裁切几何（全局约束）：百分比偏移、页码切分、
格子尺寸一律交 jobs/core。异常一律收敛成状态栏文字，不得外抛——
窗口化 exe 没有控制台，抛出去就是静默闪退。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from photoprint import jobs
from photoprint.app import view, worker
from photoprint.app.preview_view import PreviewView
from photoprint.core import modes, render, specs, store

MODE_LABELS = (
    ("自动", None),
    ("完整放入（留白）", modes.FIT_TO_PRINTABLE),
    ("铺满可打印区（留白边）", modes.FILL_PRINTABLE),
    ("出血拼版（需人工裁切）", modes.BLEED_TRIM),
)
DPI_CHOICES = ((150.0, "150"), (300.0, "300"), (600.0, "600"))
DEBOUNCE_MS = 250
OFFSET_MAX_PCT = 50
THUMB_PX = 40
IMAGE_FILTER = "图片 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp)"
ERROR_COLOR = "#b00000"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")


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
        self._count_last = None    # 上次每页格数（检测结构性布局变更）
        self.job = None
        self._thread = None
        self._task = None
        self._gen = 0
        self._stale = []        # wait 超时没停干净的旧线程，留住引用防其在跑时被回收
        self.setWindowTitle("相片打印助手")
        self._build_ui()
        self._load_printers()
        # debounce 必须先于恢复设置建好： setCurrentIndex 一类调用会打到信号
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._refresh)
        for w in (self.sheet_box, self.cell_box, self.mode_box, self.gap_box,
                  self.bleed_box, self.dpi_box, self.h_slider, self.v_slider):
            _connect_param_changed(w, self._debounce.start)
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
        self.photo_list.setFixedWidth(260)   # 只钉宽；高度不封顶，随窗口纵向伸展
        self.photo_list.setIconSize(QSize(THUMB_PX, THUMB_PX))
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

        self.preview = PreviewView()
        self.preview.cellClicked.connect(self._on_cell_clicked)
        body.addWidget(self.preview, 1)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.next_btn = QPushButton("下一页")
        self.prev_btn.clicked.connect(lambda: self._go_page(-1))
        self.next_btn.clicked.connect(lambda: self._go_page(1))
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)
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
        try:
            self.job = jobs.build_job(self.st, photos, p["sheet_key"], p["cell_key"],
                                      gap_mm=p["gap_mm"], bleed_mm=p["bleed_mm"],
                                      mode=p["mode"], offset_pct=p["offset_pct"],
                                      rotations=rotations)
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
        row = self.photo_list.currentRow()
        if 0 <= row < len(self.pool):
            self.place(slot, row)           # 选库图 + 点格 → 放入（与 2b 同入口）
        else:
            self._current_cell = slot       # 无选中 → 纯选中，供旋转/清空格
        self._highlight_current_cell()

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
            self.pool.append({"path": str(path), "img": None})
            item = QListWidgetItem(self._photo_item_text(name, None))
            item.setForeground(QColor(ERROR_COLOR))
            self.photo_list.addItem(item)
            self._set_status(f"无法读取 {name}：{exc}", error=True)
            return
        self.pool.append({"path": str(path), "img": img})
        item = QListWidgetItem(self._photo_item_text(name, img))
        item.setIcon(QIcon(view.to_thumbnail(img, THUMB_PX)))
        self.photo_list.addItem(item)

    @staticmethod
    def _photo_item_text(name, img):
        """列表项文字：旋转已移到格上，不再有角度段。"""
        if img is None:
            return f"{name}（读取失败）"
        return f"{name}  {img.width}×{img.height}px"

    def _on_rotate(self):
        self.rotate_cell(self._current_cell)

    def _on_clear_photos(self):
        self.pool = []
        self.placements = {}
        self.cell_rot = {}
        self._pages = 1
        self.page_index = 0
        self._current_cell = None
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

    def _on_print(self):
        """直打全部页：先同步落最新 job（含旋转/偏移），渲染交 render_all（关遮罩，
        I-2），走 gdi_print.print_pages(prompt=True) 弹驱动页选介质。异常全兜成
        状态栏，不外抛。"""
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
            images = jobs.render_all(self.job, dpi, show_mask=False)   # I-2
            res = gdi_print.print_pages(self.api, printer, images,
                                        self.job.sheet, dpi, prompt=True)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._set_status(f"打印失败：{exc}", error=True)
            return
        QApplication.restoreOverrideCursor()
        if res.get("cancelled"):                    # W-1：驱动页取消，非错误
            self._set_status("已取消")
        elif res["ok"]:
            msg = f"已发送 {res['pages']} 页到 {printer}"
            if res.get("degraded"):                 # W-3：降级仍成功，附提示
                msg += "（未能打开驱动设置页，已用驱动当前介质）"
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
            "offset_pct": [self.h_slider.value(), self.v_slider.value()],
            "out_dir": out_dir or self._last_out_dir(),
            "pool_paths": [e["path"] for e in self.pool],
            "placements": {str(s): pi for s, pi in self.placements.items()},
            "cell_rot": {str(s): a for s, a in self.cell_rot.items() if a},
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
        pct = job.get("offset_pct")
        if isinstance(pct, (list, tuple)) and len(pct) == 2:
            self._safe(lambda: self._apply_offset(pct))
        new_shape = ("placements" in job) or ("pool_paths" in job)
        paths = job.get("pool_paths") if new_shape else job.get("photo_paths")
        for pth in (paths if isinstance(paths, (list, tuple)) else []):
            self.append_photo(str(pth))    # 坏图走标红占位、保留库下标对齐
        self._ensure_count()
        if new_shape:
            self._safe(lambda: self._restore_placements(job))
        else:
            self._safe(lambda: self._migrate_sequential(job))

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
