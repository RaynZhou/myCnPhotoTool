# 导入文件夹（增量①）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有"添加照片→顺序填充"模型内新增「导入文件夹…」入口，把一个目录顶层的受支持图片按文件名排序批量加入照片列表。

**Architecture:** 一个无 Qt 的纯函数 `list_folder_images(dir)` 负责枚举/筛选/排序，`MainWindow.import_folder(dir)` 复用既有 `append_photo` 逐张入列并末尾单次 debounce。布局几何、渲染、模式全部不动，CLI 顺序填充逐字冻结不受影响。

**Tech Stack:** PySide6（QPushButton/QFileDialog.getExistingDirectory）、pathlib（顶层枚举）、Pillow（测试造图）、pytest（offscreen GUI）。

## Global Constraints

- 过渡约束：本增量**不得**移除/改动"添加照片→顺序填充"路径（spec §0）；`append_photo`、`_on_add_photos`、`_on_clear_photos`、`_on_rotate` 行为不变。
- 分层：布局 mm/像素与裁切几何一律交 jobs/core，本层不碰；枚举是文件系统操作，允许留在 app 层（非几何）。
- 异常收敛：窗口化 exe 无控制台，枚举/读目录异常一律降级为空结果/状态栏文字，不外抛（spec §4）。
- 扩展名口径：`IMAGE_EXTS` 与 `IMAGE_FILTER` 的扩展名集合必须一致，测试钉等（spec §3）。
- 排序确定：仅顶层、扩展名大小写不敏感、按路径小写排序，不依赖文件系统原始枚举顺序（spec §2.2）。
- `IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")`。
- 测试全部脱机 `offscreen`（conftest 已设）。

---

### Task 1: `list_folder_images` 纯枚举函数

**Files:**
- Modify: `photoprint/app/main_window.py`（模块级新增 `IMAGE_EXTS` 常量 + `list_folder_images` 函数）
- Test: `tests/test_folder_import.py`（新建）

**Interfaces:**
- Consumes: 无（纯函数，只依赖 `pathlib.Path` 与模块常量 `IMAGE_EXTS`）。
- Produces: `list_folder_images(dir_path) -> list[str]`（顶层、按扩展名大小写不敏感筛选、按路径小写排序；目录不存在/不可读返回 `[]`）；模块常量 `IMAGE_EXTS`。Task 2 依赖这两者。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_folder_import.py`：

```python
"""导入文件夹：枚举与批量入列，脱机、不碰目录对话框。"""
import os

import pytest

pytest.importorskip("PIL", reason="需要 Pillow")
pytest.importorskip("PySide6", reason="需要 Qt 绑定")

from PIL import Image  # noqa: E402

from photoprint.app.main_window import IMAGE_EXTS, IMAGE_FILTER, list_folder_images  # noqa: E402


def _mk(dirpath, name, size=(40, 30)):
    Image.new("RGB", size, (10, 20, 30)).save(str(dirpath / name))


def _basenames_sorted(paths):
    return sorted(os.path.basename(p).lower() for p in paths)


def test_list_folder_images_filters_and_sorts(tmp_path):
    _mk(tmp_path, "c.jpg")
    _mk(tmp_path, "b.png")
    _mk(tmp_path, "a.tif")
    (tmp_path / "notes.txt").write_text("hi")          # 非图片，忽略
    sub = tmp_path / "sub"
    sub.mkdir()
    _mk(sub, "z.jpg")                                   # 子目录，忽略
    assert _basenames_sorted(list_folder_images(str(tmp_path))) == \
        ["a.tif", "b.png", "c.jpg"]


def test_list_folder_images_case_insensitive_ext(tmp_path):
    _mk(tmp_path, "UPPER.JPG")                          # 大写扩展名要收
    got = list_folder_images(str(tmp_path))
    assert len(got) == 1 and got[0].lower().endswith(".jpg")


def test_list_folder_images_missing_dir_returns_empty(tmp_path):
    assert list_folder_images(str(tmp_path / "nope")) == []


def test_image_exts_match_filter():
    """IMAGE_EXTS 与对话框 IMAGE_FILTER 的扩展名集合必须同源，否则能选不能列。"""
    filt = IMAGE_FILTER.split("(")[1].split(")")[0]
    from_filter = {t.lstrip("*").lower() for t in filt.split()}
    assert set(IMAGE_EXTS) == from_filter
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_folder_import.py -q`
Expected: FAIL — `ImportError: cannot import name 'list_folder_images'`（或 `IMAGE_EXTS`）。

- [ ] **Step 3: 写最小实现**

`photoprint/app/main_window.py` 常量区现有：

```python
IMAGE_FILTER = "图片 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp)"
ERROR_COLOR = "#b00000"
```

在其后补充：

```python
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")


def list_folder_images(dir_path):
    """顶层、按 IMAGE_EXTS（大小写不敏感）筛选、按路径小写排序的图片路径。

    目录不存在/不可读一律返回 []——窗口化 exe 无控制台，异常外抛即静默闪退。
    仅取文件、不递归子目录（增量①明确排除递归，见 spec §2.2）。
    """
    try:
        entries = list(Path(dir_path).iterdir())
    except (OSError, ValueError):
        return []
    imgs = [str(p) for p in entries
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return sorted(imgs, key=lambda s: s.lower())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_folder_import.py -q`
Expected: PASS（4 个）。

- [ ] **Step 5: 变异验牙**

- 把 `p.suffix.lower()` 改成 `p.suffix`（大小写敏感）→ `test_list_folder_images_case_insensitive_ext` 转红。
- 删 `sorted(...)` 的 `key=lambda s: s.lower()` 保留 `sorted`（或整体删排序）→ 视文件系统顺序，`filters_and_sorts` 有概率转红；为确保有牙，改测试数据使 `iterdir` 原生序非字典序（Windows 一般按创建序，`c/b/a` 的建序即证）。
- 把 `p.is_file()` 去掉（放行目录）→ `filters_and_sorts` 的 `sub` 目录名混入使断言转红。
逐项还原；全仓 `Grep regex=MUTATION-TEMP` 命中 0。

- [ ] **Step 6: 提交**

```bash
git add photoprint/app/main_window.py tests/test_folder_import.py
git commit -m "feat(ui): 新增 list_folder_images 顶层图片枚举（排序+容错）"
```

---

### Task 2: `import_folder` 批量入列 + 「导入文件夹…」按钮

**Files:**
- Modify: `photoprint/app/main_window.py`（按钮行新增 `import_btn`；新增 `import_folder` 与 `_on_import_folder` 方法）
- Test: `tests/test_folder_import.py`（追加 GUI 测试）

**Interfaces:**
- Consumes: `list_folder_images(dir_path)`（Task 1）、`MainWindow.append_photo`、`MainWindow._debounce`、`MainWindow._set_status`、`MainWindow._start_dir`（均既有）。
- Produces: `MainWindow.import_folder(dir_path) -> int`、`MainWindow._on_import_folder`；按钮 `objectName == "import_btn"`。

- [ ] **Step 1: 写失败测试**

`tests/test_folder_import.py` 顶部 import 段补充（Qt 组件与待测类）：

```python
from PySide6.QtCore import QElapsedTimer, QEventLoop  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402

from photoprint.app.main_window import MainWindow  # noqa: E402
from photoprint.core import store  # noqa: E402
```

并在 `_mk` 下方新增临时 store 助手与一个收尾夹具（与 `test_app_main_window.py` 同口径）：

```python
def _store(tmp_path):
    s = store.Store(tmp_path / "papers.json")
    s.load()
    return s
```

> 收尾夹具必须加：`MainWindow.__init__` 末尾会 `_refresh()` 起一条渲染线程；不泵不关
> 就在进程退出时把在跑的 QThread 拖回被析构→硬崩（0xC0000409）。

```python
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
```

文件末尾追加：

```python
def test_import_folder_adds_sorted(qapp, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _mk(src, "c.jpg")
    _mk(src, "b.png")
    _mk(src, "a.tif")
    w = MainWindow(st=_store(tmp_path))
    n = w.import_folder(str(src))
    assert n == 3
    assert w.photo_list.count() == 3
    assert len(w.photos) == 3
    # 列表文字按 a/b/c 顺序（append 序 = 排序序）
    texts = [w.photo_list.item(i).text() for i in range(3)]
    assert texts[0].startswith("a.tif") and texts[1].startswith("b.png") \
        and texts[2].startswith("c.jpg")


def test_import_folder_bad_image_flags_and_continues(qapp, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _mk(src, "good.jpg")
    (src / "broken.jpg").write_bytes(b"not an image")
    w = MainWindow(st=_store(tmp_path))
    n = w.import_folder(str(src))
    assert n == 2                                  # 两张都识别入列
    assert w.photos.count(None) == 1               # 坏图为 None 占位
    # 排序：broken.jpg < good.jpg
    assert w.photo_list.item(0).text().startswith("broken")
    assert "（读取失败）" in w.photo_list.item(0).text()


def test_import_folder_empty_dir_no_change(qapp, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    w = MainWindow(st=_store(tmp_path))
    n = w.import_folder(str(src))
    assert n == 0
    assert w.photo_list.count() == 0
    assert "没有可导入的图片" in w.statusBar().currentMessage()


def test_import_folder_missing_dir_returns_zero(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    assert w.import_folder(str(tmp_path / "nope")) == 0
    assert w.photo_list.count() == 0


def test_import_button_exists(qapp, tmp_path):
    w = MainWindow(st=_store(tmp_path))
    btns = w.findChildren(QPushButton)
    assert any(b.objectName() == "import_btn" for b in btns)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_folder_import.py -k "import_folder or import_button" -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute 'import_folder'`。

- [ ] **Step 3a: 新增按钮**

`_build_ui` 中现有按钮行：

```python
        add_btn = QPushButton("添加照片…")
        add_btn.clicked.connect(self._on_add_photos)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._on_clear_photos)
```

在 `add_btn` 与 `clear_btn` 之间插入：

```python
        import_btn = QPushButton("导入文件夹…")
        import_btn.setObjectName("import_btn")
        import_btn.clicked.connect(self._on_import_folder)
```

并把 `btns` 组装改为在 add 与 clear 之间加入 import：

```python
        btns = QHBoxLayout()
        btns.addWidget(add_btn)
        btns.addWidget(import_btn)
        btns.addWidget(clear_btn)
        btns.addWidget(rotate_btn)
        panel.addRow("", btns)
```

- [ ] **Step 3b: 新增方法**

`photoprint/app/main_window.py` 在 `_on_add_photos` 方法之后插入：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_folder_import.py -q`
Expected: PASS（Task1 4 + Task2 5 = 9）。

- [ ] **Step 5: 变异验牙**

- 把 `if not paths:` 分支删掉（空目录也走循环+debounce）→ `test_import_folder_empty_dir_no_change` 的"没有可导入的图片"文案断言转红（被"已导入 0 张"覆盖或状态不同）。
- 把末尾 `self._debounce.start()` 移到 for 内 → 用 `test_import_folder_adds_sorted` 不变、但补一条最小调用计数侧证可选；至少确认移出 for 后仍绿、移进 for 不崩（本条为防"每张都刷"回归，可选断言）。
- 删 `import_btn.setObjectName("import_btn")` → `test_import_button_exists` 转红。
逐项还原；`Grep regex=MUTATION-TEMP` 命中 0。

- [ ] **Step 6: 全量回归（过渡约束）**

Run: `python -m pytest tests/ -q`
Expected: 全绿——既有 `_on_add_photos`/顺序填充/旋转/导出/持久化测试不受扰动。

- [ ] **Step 7: 提交**

```bash
git add photoprint/app/main_window.py tests/test_folder_import.py
git commit -m "feat(ui): 新增「导入文件夹」批量入列（复用顺序填充，末尾单次刷新）"
```

---

## 手工验收（spec §7）

重新 `build_exe.ps1` 打包后：点「导入文件夹…」选含多张照片的目录 → 列表按文件名顺序出现这些照片（带缩略图），预览按现有顺序模型自动填充；含子目录/非图片/坏图时表现符合 spec §2/§4；空目录或取消只给状态栏提示、不改布局。
