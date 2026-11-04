# 相片打印助手（PhotoPrint）

## 它解决什么问题
佳能 Easy-PhotoPrint Editor 的相纸预设里没有 3R（5寸 89×127mm），但 G3800 驱动
支持自定义尺寸（宽 55–215.9mm、长 89–676mm），所以 5寸能打，只是官方软件没给入口。
本工具补齐 3R 及任意自建尺寸，并支持大纸拼版多张小图。

## 已知物理限制（勿绕过）
- 自定义尺寸不支持无边距 ⇒ 5寸直打必然留白边（依官方规格约 上3/下5/左右3.4mm）。
- 想要无边距 5寸：选 A4 + 3mm 出血拼版，打印后沿灰裁切线人工裁开。
- 12寸（254×305mm）超出 G3800 能力，已被阻断。

## 安装与运行
pip install -r requirements.txt
python -m photoprint.cli --photos 1.jpg 2.jpg 3.jpg 4.jpg --sheet A4 --cell 3R --out _lab/out/page.png
python -m photoprint.cli --photos *.jpg --sheet A4 --cell 3R --print --printer "Canon G3800 series"
python -m pytest -q            # 全部几何断言
python _lab/m1m2_check.py      # 本机可验证的端到端证据

## 驱动里建立 3R 表单（一次性，之后直打更稳）
1. 控制面板 → 设备和打印机 → Canon G3800 → 打印首选项 → 页设置
2. 纸张尺寸选"自定义"，宽 89mm、高 127mm，命名 "3R"，保存
3. 需无边距的 6寸：在同一面板把布局设为"无边距"，本工具会继承该私有设置
（若驱动保存后仍不出现该尺寸，改用 --pdf 路径：页面尺寸已是 89×127mm）
