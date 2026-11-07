"""极简扁平设计系统的单一出处：色板、字体、圆角、间距与全局 QSS。

风格口径（StyleKit「极简扁平」）：白底 + 单一强调色 + 中性灰层级，靠留白与
1px 细线分区；无阴影、无渐变、无纹理；控件统一圆角。

本模块只依赖 Qt，不读任何外部资源文件——样式全用 Python 字符串承载，onefile
exe 不必往 PhotoPrint.spec 里加 datas 也能完整生效。反向依赖必须为空：app 层
其他模块（main_window / preview_view）引用这里，这里绝不引用它们，否则成环。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QVBoxLayout)

# ---------- 色板 ----------

BG = "#F5F6F8"           # 窗口底色
SURFACE = "#FFFFFF"      # 卡片底
LINE = "#E5E7EB"         # 细线分隔
LINE_STRONG = "#D6DAE0"  # 控件边/预览格线
TEXT = "#1F2329"         # 主文字
TEXT_MUTED = "#6B7280"   # 次要文字
ACCENT = "#2563EB"       # 唯一强调色
ACCENT_HOVER = "#1D4ED8"
ACCENT_PRESSED = "#1E40AF"
ACCENT_SOFT = "#EAF1FE"  # 选中/悬停浅底
ACCENT_PALE = "#BFD4FB"  # 禁用态强调色
CANVAS = "#EDEFF3"      # 预览区底色（白纸浮在浅灰上，不用阴影）
DANGER = "#B00000"       # 错误红（与 main_window.ERROR_COLOR 同值）

# ---------- 字体与间距 ----------

FONT_FAMILY = "Microsoft YaHei UI"
FONT_FALLBACK = ("Microsoft YaHei", "Segoe UI", "sans-serif")
FONT_SIZE_PT = 9

# 左区固定宽：照片列 + 设置列。照片列要容下两列缩略图——IconMode 每格由
# 图标 120 + QSS 内边距 6×2 + 描边 1×2 + 委托边距撑到 140px，两列要 viewport
# ≥ 283px，而 viewport ≈ 列宽 - 40，所以列宽取 344（304 视口，留 24px 余量）。
# 324 时只差几像素，缩略图就全挤成一列、卡片右侧空一大块。
# 设置列 360 让「铺满可打印区（留白边）」这类长选项名与半宽字段都不被截断。
# 两列并排后表单不再纵向堆到需要滚动——这是「默认开窗就看全左区」的前提。
PHOTO_COL_W = 344
PANEL_COL_W = 360
COL_GAP = 12
PAGE_MARGIN = 16
LEFT_W = 2 * PAGE_MARGIN + PHOTO_COL_W + COL_GAP + PANEL_COL_W   # 748
CARD_PAD = 14
ROW_GAP = 10
CARD_GAP = 12
RADIUS_CTRL = 6
RADIUS_CARD = 10
# 字段名列宽：左对齐后所有控件的左边线整齐成一条竖线（右对齐会让短标签的
# 左沿参差，在窄卡片里最显乱）。两档宽度配两种卡片的信息密度。
LABEL_W = 62
LABEL_W_SMALL = 46

_FONT_CSS = ', '.join([f'"{FONT_FAMILY}"'] + [f'"{f}"' for f in FONT_FALLBACK])

APP_QSS = f"""
* {{
    font-family: {_FONT_CSS};
}}
QMainWindow, QWidget#Root {{
    background: {BG};
}}
QWidget {{
    color: {TEXT};
    font-size: {FONT_SIZE_PT}pt;
}}

/* ---------- 卡片与分区 ---------- */

QFrame#Card {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#PreviewCard {{
    background: {CANVAS};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#ActionBar {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#Divider {{
    border: none;
    background: {LINE};
    min-height: 1px;
    max-height: 1px;
}}
QScrollArea#Sidebar, QWidget#SidebarContent {{
    background: transparent;
    border: none;
}}
QScrollArea#Sidebar {{
    border-right: 1px solid {LINE};
}}

/* ---------- 文字层级 ---------- */

QLabel {{
    background: transparent;
    color: {TEXT};
}}
QLabel#AppTitle {{
    font-size: 15pt;
    font-weight: 600;
}}
QLabel#CardTitle {{
    font-size: 10.5pt;
    font-weight: 600;
}}
QLabel#Hint, QLabel#FieldLabel {{
    font-size: 8.5pt;
    color: {TEXT_MUTED};
}}
QLabel#PageLabel {{
    color: {TEXT_MUTED};
    padding: 0 4px;
}}
QLabel#PreviewView {{
    background: transparent;
    color: {TEXT_MUTED};
}}

/* ---------- 按钮 ---------- */

QPushButton {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CTRL}px;
    padding: 6px 12px;
    color: {TEXT};
}}
QPushButton:hover {{
    background: {ACCENT_SOFT};
    border-color: {ACCENT_PALE};
}}
QPushButton:pressed {{
    background: #DCE9FD;
}}
QPushButton:disabled {{
    color: #9AA3AF;
    background: {BG};
    border-color: #EDEFF2;
}}
QPushButton#print_btn {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: {SURFACE};
    font-weight: 600;
    padding: 7px 20px;
}}
QPushButton#print_btn:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#print_btn:pressed {{
    background: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QPushButton#print_btn:disabled {{
    background: {ACCENT_PALE};
    border-color: {ACCENT_PALE};
    color: {SURFACE};
}}

/* ---------- 输入控件 ---------- */

QComboBox, QLineEdit, QDoubleSpinBox {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CTRL}px;
    padding: 4px 8px;
    min-height: 18px;
    selection-background-color: {ACCENT};
    selection-color: {SURFACE};
}}
QComboBox:hover, QLineEdit:hover, QDoubleSpinBox:hover {{
    border-color: #C7D2E3;
}}
QComboBox:focus, QLineEdit:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}
QComboBox:disabled, QLineEdit:disabled, QDoubleSpinBox:disabled {{
    color: #9AA3AF;
    background: {BG};
    border-color: #EDEFF2;
}}
/* 不改 ::drop-down / ::down-arrow：Qt 画不出 CSS 三角形，自绘图片又要外部
   资源；把箭头交给 Fusion 原生绘制，任何情况下都能看见“这是下拉” */
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: {RADIUS_CTRL}px;
    padding: 4px;
    outline: 0;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 14px;
    border: none;
    background: transparent;
}}

/* ---------- 勾选框 ---------- */

QCheckBox {{
    background: transparent;
    spacing: 8px;
    padding: 2px 0;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid #C7CEDA;
    border-radius: 4px;
    background: {SURFACE};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QCheckBox:disabled {{
    color: #9AA3AF;
}}
QCheckBox::indicator:disabled {{
    background: {BG};
    border-color: {LINE};
}}
QCheckBox::indicator:checked:disabled {{
    background: {ACCENT_PALE};
    border-color: {ACCENT_PALE};
}}

/* ---------- 滑块 ---------- */

QSlider::groove:horizontal {{
    height: 3px;
    background: {LINE};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
    background: {SURFACE};
    border: 2px solid {ACCENT};
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT_SOFT};
}}
QSlider::handle:horizontal:disabled {{
    border-color: #C7CEDA;
    background: {BG};
}}

/* ---------- 滚动条 ---------- */

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #D2D7DE;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: #B6BDC8;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #D2D7DE;
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #B6BDC8;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---------- 列表 / 菜单 / 状态栏 ---------- */

QListView {{
    background: transparent;
    border: none;
    outline: 0;
}}
QMenu {{
    background: {SURFACE};
    border: 1px solid {LINE};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 18px 6px 14px;
    border-radius: {RADIUS_CTRL}px;
    color: {TEXT};
}}
QMenu::item:selected {{
    background: {ACCENT_SOFT};
    color: {TEXT};
}}
QMenu::separator {{
    height: 1px;
    background: {LINE};
    margin: 4px 6px;
}}
QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid {LINE};
    color: {TEXT_MUTED};
}}
QStatusBar::item {{
    border: none;
}}
QToolTip {{
    background: {TEXT};
    color: {SURFACE};
    border: none;
    padding: 5px 8px;
    border-radius: {RADIUS_CTRL}px;
}}
"""


# ---------- 装配 ----------

def base_font():
    """全局基准字体：微软雅黑，9pt（中文界面在 96dpi 下最稳的档）。"""
    font = QFont(FONT_FAMILY)
    font.setPointSize(FONT_SIZE_PT)
    font.setStyleStrategy(QFont.PreferAntialias)
    return font


def install_app_style():
    """把基础风格切到 Fusion：QSS 对 combo/check 等子控件才可预期。

    Windows 原生主题里这些子控件由系统绘制，QSS 部分规则会被忽略（圆角与
    指示器不一致）。异常一律吞掉——窗口化 exe 无控制台，抛出去就是静默闪退。
    """
    app = QApplication.instance()
    if app is None:
        return
    try:
        if app.style().objectName().lower() != "fusion":
            app.setStyle("Fusion")
    except Exception:
        pass


def apply(window):
    """给窗口装上字体与全局样式（每窗口一份，不污染 QApplication 单例）。"""
    install_app_style()
    window.setFont(base_font())
    window.setStyleSheet(APP_QSS)


# ---------- 小组件工厂 ----------

def card(title, subtitle=None):
    """白底卡片：返回 (QFrame#Card, 卡片内容 QVBoxLayout)。

    标题行独立于内容区：主标题 600 字重，副标题走 Hint 弱化色，二者同排。
    """
    frame = QFrame()
    frame.setObjectName("Card")
    col = QVBoxLayout(frame)
    col.setContentsMargins(CARD_PAD, CARD_PAD, CARD_PAD, CARD_PAD)
    col.setSpacing(ROW_GAP)
    head = QHBoxLayout()
    head.setSpacing(8)
    title_lb = QLabel(title)
    title_lb.setObjectName("CardTitle")
    head.addWidget(title_lb)
    if subtitle:
        sub_lb = QLabel(subtitle)
        sub_lb.setObjectName("Hint")
        head.addWidget(sub_lb)
    head.addStretch(1)
    col.addLayout(head)
    body = QVBoxLayout()
    body.setSpacing(ROW_GAP)
    col.addLayout(body, 1)
    return frame, body


def divider():
    """1px 分隔细线（扁平风里代替色块分组的主要手段）。"""
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.NoFrame)
    line.setFixedHeight(1)
    return line


def field_label(text):
    """字段名小标签：8.5pt 弱化色、左对齐，配字段网格使用。"""
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return label


def grid_cell(grid, row, col, text, widget, label_w=None, span=1):
    """往网格里塞一组「标签 + 控件」：标签在 col 列，控件紧随其后一列。

    标签给固定宽度并左对齐——短标签（字号）与长标签（输出 dpi）各占各的，
    但所有控件左边线仍落在同一条竖线上。span > 1 让控件横跨多列（整行字段）。
    """
    label = field_label(text)
    if label_w:
        label.setFixedWidth(label_w)
    grid.addWidget(label, row, col)
    grid.addWidget(widget, row, col + 1, 1, span)


def field_grid(entries, per_row=2, label_w=LABEL_W_SMALL):
    """多列表单网格：每格「左标签、右控件」，行数按 per_row 折行。

    QFormLayout 在窄侧栏里一列到底会拉出很长的表单；折成两列后同一张卡片
    能少占约一半高度，控件宽度也够显示「微软雅黑」这类选项名。
    """
    grid = QGridLayout()
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(6)
    for i, (text, widget) in enumerate(entries):
        row, col = divmod(i, per_row)
        grid_cell(grid, row, col * 2, text, widget, label_w)
        grid.setColumnStretch(col * 2 + 1, 1)
    return grid


def swatch_style(rgb):
    """颜色按钮的内联样式：实心色块 + 细边，按下不改色（颜色本身是信息）。"""
    return ("background:rgb(%d,%d,%d);border:1px solid %s;border-radius:%dpx;"
            % (rgb[0], rgb[1], rgb[2], LINE_STRONG, RADIUS_CTRL))
