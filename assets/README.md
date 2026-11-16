# README Logo

`domino-logo.gif` 是 README 顶部的循环动画；点击它可查看静态的 `domino-logo.png`。

像素字形来自 `src/domino_tui.py` 的 `LOGO_LINES`，保留品牌青绿色，使用白色背景和浅灰阴影。六个字母从左到右绕底部依次倒下，再从右到左立起；周期 5.2 秒。原始画布为 640 × 188，README 按 420 像素宽展示。GIF 使用共享调色板与帧合并，避免颜色闪烁并控制体积。

重新生成需要 Pillow，仅用于文档资产，不是 Domino 运行依赖：

```bash
.venv/bin/python -m pip install Pillow
.venv/bin/python scripts/render_logo.py
```

检查逐帧动作可生成联系表：

```bash
.venv/bin/python scripts/render_logo.py --contact-sheet dist/readme-logo-contact.png
```
