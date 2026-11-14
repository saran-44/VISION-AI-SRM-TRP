# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the gate portal.

Build with desktop/gate/build_gate.ps1, not by hand: the script installs the
CPU torch wheel first, which is the difference between a 700 MB bundle and a
4 GB one.

The portal imports its vision stack lazily (`from .vision import ...` inside a
function), so PyInstaller cannot see those imports by following the code. They
are listed in `hiddenimports` — without them the bundle starts, serves the
portal, and reports "no detector" the first time an operator scans.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[2]  # noqa: F821 - injected by PyInstaller

# The portal, the checkpoints, and the gate launcher itself.
datas = [
    (str(ROOT / "frontend"), "frontend"),
    (str(ROOT / "best.pt"), "."),
    (str(ROOT / "anpr_best.pt"), "."),
]
vehicle_model = ROOT / "weights" / "vehicle.pt"
if vehicle_model.exists():
    datas.append((str(vehicle_model), "weights"))
else:
    print("WARNING: weights/vehicle.pt is missing; the vehicle stage will be skipped")

# Heavy packages that ship model files, DLLs or plugin directories.
binaries = []
hiddenimports = [
    "waitress",
    "waitress.server",
    "pystray._win32",
    "backend.app",
    "backend.preflight",
    "backend.frame_source",
    "backend.vision",
    "backend.seed_demo",
    "cv2",
    "PIL._tkinter_finder",
]
for package in ("ultralytics", "rapidocr_onnxruntime", "onnxruntime", "torch", "torchvision", "pystray"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception as exc:  # a package that is not installed is a missing stage, not a failed build
        print(f"WARNING: could not collect {package}: {exc}")
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
hiddenimports += collect_submodules("backend")

a = Analysis(  # noqa: F821
    [str(ROOT / "desktop" / "gate" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib.backends._backend_gtk", "tkinter.test", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VisionAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A console program on purpose: `--setup` reads the administrator email
    # and password, and `--check` prints the report. The launcher hides the
    # console window (hide_console) when it is only serving the portal, so a
    # double-click still leaves no black window on the gate desk.
    console=True,
    icon=str(ROOT / "desktop" / "gate" / "visionai.ico"),
    version=None,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VisionAI",
)
