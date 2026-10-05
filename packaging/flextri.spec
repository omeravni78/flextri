# PyInstaller recipe for the flexTri desktop app. Build from the repo root:
#     pyinstaller packaging/flextri.spec --noconfirm
# Result: dist/flexTri/ (Windows, Linux) or dist/flexTri.app (macOS). Builds only for the OS it runs on.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
datas = collect_data_files("flextri")  # templates, static files, plans, icon
hiddenimports = collect_submodules("uvicorn") + collect_submodules("flextri")
binaries = []
for pkg in ("garminconnect", "curl_cffi", "ua_generator"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# pystray picks its tray backend at import time, which fails without a display (as on a build
# machine), so its backends are named here instead of collected.
hiddenimports += ["pystray", "pystray._base", "pystray._util", "PIL.Image"] + {
    "win32": ["pystray._win32", "pystray._util.win32"],
    "darwin": ["pystray._darwin"],
}.get(sys.platform, ["pystray._xorg", "pystray._appindicator", "pystray._gtk", "pystray._util.gtk",
                     "pystray._util.notify_dbus"])

icon = ROOT / "packaging" / "build" / ("flextri.ico" if sys.platform == "win32" else "flextri.icns")
icon = str(icon) if icon.exists() else None

a = Analysis([str(ROOT / "packaging" / "flextri_app.py")], pathex=[str(ROOT / "src")], datas=datas,
             binaries=binaries, hiddenimports=hiddenimports, excludes=["tkinter", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="flexTri", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="flexTri")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="flexTri.app", icon=icon, bundle_identifier="com.github.omeravni78.flextri",
                 version=__import__("flextri").__version__,
                 info_plist={"LSUIElement": False, "NSHighResolutionCapable": True,
                             "LSMinimumSystemVersion": "12.0"})
