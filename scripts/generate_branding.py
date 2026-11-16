"""Generate all branding assets from the attached logo file.

Sizes generated:
- favicon.ico: 16, 32, 48, 64, 128, 256
- app.ico: 16, 32, 48, 64, 128, 256
- installer 256px PNG
- dashboard header logo
"""
from __future__ import annotations

import shutil
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
UPLOADED_LOGO = Path(r"C:/Users/kp571/.gemini/antigravity/brain/a9cec8c0-02d7-4b8c-9100-29bd82866f9a/.user_uploaded/media_1794835620418_453a57c4.png")

def main():
    if not UPLOADED_LOGO.exists():
        print(f"Branding deferred - no logo file found at {UPLOADED_LOGO}")
        return 1

    print(f"Found logo at: {UPLOADED_LOGO}")
    
    # 1. Project root logo.png
    dest_logo = ROOT / "logo.png"
    shutil.copyfile(UPLOADED_LOGO, dest_logo)
    print(f"Wrote: {dest_logo}")

    img = Image.open(UPLOADED_LOGO).convert("RGBA")
    
    # 2. Frontend assets
    frontend_assets = ROOT / "frontend" / "assets"
    frontend_assets.mkdir(parents=True, exist_ok=True)
    
    # Copy full logo to frontend/assets/logo.png
    dest_frontend_logo = frontend_assets / "logo.png"
    shutil.copyfile(UPLOADED_LOGO, dest_frontend_logo)
    print(f"Wrote: {dest_frontend_logo}")

    # Header logo (height 64px or width 256px for sharp display)
    header_img = img.resize((256, 256), Image.Resampling.LANCZOS)
    header_path = frontend_assets / "logo-header.png"
    header_img.save(header_path, format="PNG")
    print(f"Wrote: {header_path}")

    # favicon.ico (16, 32, 48, 64, 128, 256)
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    favicon_path = frontend_assets / "favicon.ico"
    img.save(favicon_path, format="ICO", sizes=ico_sizes)
    print(f"Wrote: {favicon_path}")

    # 3. Desktop assets
    gate_assets = ROOT / "desktop" / "gate" / "assets"
    gate_assets.mkdir(parents=True, exist_ok=True)
    
    app_ico_gate = ROOT / "desktop" / "gate" / "app.ico"
    img.save(app_ico_gate, format="ICO", sizes=ico_sizes)
    print(f"Wrote: {app_ico_gate}")

    app_ico_assets = gate_assets / "app.ico"
    img.save(app_ico_assets, format="ICO", sizes=ico_sizes)
    print(f"Wrote: {app_ico_assets}")

    installer_png = gate_assets / "installer_256.png"
    installer_img = img.resize((256, 256), Image.Resampling.LANCZOS)
    installer_img.save(installer_png, format="PNG")
    print(f"Wrote: {installer_png}")

    print("All branding assets generated successfully.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
