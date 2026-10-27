"""Render'daki ampul ve lambalara yumuşak ışık parıltısı (bloom) ekler.

Kullanım:  python3 parlama.py <girdi.png> <cikti.jpg>
"""
import sys

import numpy as np
from PIL import Image, ImageFilter

src, dst = sys.argv[1], sys.argv[2]
img = Image.open(src).convert("RGB")
a = np.asarray(img).astype(np.float32) / 255.0

# Parlak bölgeleri ayıkla (yalnızca lamba çekirdekleri ve yakın çevresi)
lum = a @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
mask = np.clip((lum - 0.82) / 0.18, 0, 1)[..., None]
bright = Image.fromarray((a * mask * 255).astype(np.uint8))

w = img.width
glow = np.zeros_like(a)
for radius, weight in ((w * 0.003, 0.55), (w * 0.012, 0.45), (w * 0.035, 0.35)):
    glow += np.asarray(bright.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32) / 255.0 * weight

# Sıcak tonlu parıltı, ekran (screen) karışımı
glow *= np.array([1.0, 0.78, 0.55], dtype=np.float32)
out = 1 - (1 - a) * (1 - np.clip(glow, 0, 1))

# Hafif vinyet
h = a.shape[0]
yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
out *= (1 - 0.22 * np.clip(d - 0.55, 0, 1) ** 1.5)[..., None]

Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).save(dst, quality=93)
print("YAZILDI", dst)
