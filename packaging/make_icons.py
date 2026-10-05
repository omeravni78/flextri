"""Make the Windows .ico and macOS .icns from src/flextri/data/icon.png (needs Pillow)."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "packaging" / "build"
out.mkdir(exist_ok=True)
img = Image.open(ROOT / "src" / "flextri" / "data" / "icon.png")
img.save(out / "flextri.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
img.save(out / "flextri.icns")
img.save(out / "flextri.png")
