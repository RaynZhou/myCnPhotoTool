# 相片打印助手（PhotoPrint）

## 它解决什么问题
佳能 Easy-PhotoPrint Editor 的相纸预设里没有 3R（5寸 89×127mm），但 G3800 驱动
支持自定义尺寸（宽 55–215.9mm、长 89–676mm），所以 5寸能打，只是官方软件没给入口。
本工具补齐 3R 及任意自建尺寸，并支持大纸拼版多张小图。

## 已知物理限制（勿绕过）
- 自定义尺寸不支持无边距 ⇒ 5寸直打必然留边距（驱动实测不可印区 左3.4/上3.0/右3.4/下5.0mm；
  成品照片按“上下相等、左右相等”取齐后实际是 上5.1/下5.1/左右3.5mm；证件照拼版仍按逐边原值密排）。
  面板上的「边距」开关只管照片与照片之间（勾上留 2mm、不勾紧贴），纸边这圈它关不掉。
- 想要无边距 5寸：选 A4 + 3mm 出血拼版，打印后沿灰裁切线人工裁开。
- 12寸（254×305mm）超出 G3800 能力，已被阻断。
- 导出产物（PNG/PDF）不含不可印区灰遮罩；预览里看到灰边是提醒，不是成品的一部分（调试用 `--mask`）。

## 安装与运行
依赖：Pillow（读图/渲染）、pywin32（GDI 直打）、img2pdf（等尺寸 PDF）、pytest（测试）、PySide6（界面）
pip install -r requirements.txt

### 图形界面
python -m photoprint.app          # 选照片 → 选纸张/格子 → 预览 → 导出 PDF / 直接打印

### 在界面里直接打印（选介质）
选中打印机 → 调好纸张/格子/模式 → 点「打印…」即直打全部页（默认不弹驱动页；
勾上面板右下「打印前打开驱动设置页」才会先弹）。本工具保证自定义纸张尺寸
不被驱动页重置；介质与质量可在面板「介质类型/打印质量」直选，也可交给驱动。
仍建议先在驱动"打印首选项"里建好 3R 自定义纸张表单（见下）。

### 单文件 exe
.\build_exe.ps1                   # 产出 dist\PhotoPrint.exe（需联网装 pyinstaller）
.\_lab\check_exe.ps1              # 启动验收（需交互桌面会话，无桌面必 FAIL）

### 命令行
python -m photoprint.cli --photos 1.jpg 2.jpg 3.jpg 4.jpg --sheet A4 --cell 3R --out _lab/out/page.png
python -m photoprint.cli --print 需要 --printer；PowerShell 下 `--photos *.jpg` 不会展开，
请逐个列出或用 `(Get-ChildItem *.jpg).FullName`
python -m pytest -q            # 全部几何断言
python _lab/m1m2_check.py      # 本机可验证的端到端证据
python _lab/check_gui_cli_parity.py  # GUI/CLI 同图与导出无遮罩（需仓库根在 sys.path，脚本自带 bootstrap）

## 驱动里建立 3R 表单（一次性，之后直打更稳）
1. 控制面板 → 设备和打印机 → Canon G3800 → 打印首选项 → 页设置
2. 纸张尺寸选"自定义"，宽 89mm、高 127mm，命名 "3R"，保存
3. 需无边距的 6寸：在同一面板把布局设为"无边距"，本工具会继承该私有设置
（若驱动保存后仍不出现该尺寸，改用 --pdf 路径：页面尺寸已是 89×127mm）
