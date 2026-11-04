# -*- coding: utf-8 -*-
"""生成应用图标（开发时运行一次即可）。"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 1024
OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(exist_ok=True)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 外圈光晕
d.ellipse((32, 32, SIZE - 32, SIZE - 32), fill=(246, 196, 83, 38))
# 金币主体
d.ellipse((88, 88, SIZE - 88, SIZE - 88), fill=(246, 196, 83, 255), outline=(255, 230, 163, 255), width=18)
# 内圈
d.ellipse((160, 160, SIZE - 160, SIZE - 160), fill=(224, 169, 43, 255), outline=(248, 217, 123, 255), width=12)

font = None
for candidate in (
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
):
    try:
        font = ImageFont.truetype(candidate, 390)
        break
    except OSError:
        continue
if font is None:
    font = ImageFont.load_default()

text = "金"
bbox = d.textbbox((0, 0), text, font=font)
w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
d.text(((SIZE - w) / 2 - bbox[0], (SIZE - h) / 2 - bbox[1] - 12), text, font=font, fill=(42, 27, 0, 255))

img = img.resize((256, 256), Image.LANCZOS)
img.save(OUT / "icon.png")
img.save(
    OUT / "icon.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("written", OUT / "icon.ico")
