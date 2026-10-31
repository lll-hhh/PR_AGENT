"""Rasterize the original vector mark into Windows icon sizes."""

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

assets = Path(__file__).resolve().parents[1] / "merge_monitor" / "assets"
renderer = QSvgRenderer(str(assets / "mark.svg"))
image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
renderer.render(painter)
painter.end()
image.save(str(assets / "mark.png"))
with Image.open(assets / "mark.png") as source:
    source.save(assets / "merge.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("Generated mark.png and multi-resolution merge.ico")
