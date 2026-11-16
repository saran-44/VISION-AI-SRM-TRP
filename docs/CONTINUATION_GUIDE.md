# Project Continuation & Migration Guide — VISION AI - SRM TRP

This document provides a complete transition plan and handover prompt for resuming work seamlessly on a new system.

---

## 1. Master Continuation Prompt for New System

Paste the following prompt directly into your AI assistant (Cursor, Antigravity, or Claude) when opening this repository on the new machine:

```text
You are working on the VISION-AI-SRM-TRP project for SRM TRP Transport.
The project repository has completed Rounds 1 through 10 of audit remediation and stabilization.

CURRENT STATUS:
- Tests: 100% green (all backend tests pass on both SQLite and PostgreSQL).
- CI: GitHub Actions CI is passing (Backend tests, Frontend checks, Secret scan, Vision stack).
- Accuracy: 12/12 bus numbers detected across stills and video; 3/3 still plates detected.
- Desktop Gate App: Single-process runner implemented in desktop/gate/launcher.py with fallback batch runner desktop/gate/start_gate.bat, desktop shortcut installer desktop/gate/install_shortcut_and_task.ps1, %APPDATA%\VisionAI configuration, port collision resolution, and clean shutdown.
- Operational Runbook: docs/RUNBOOK.md created with operator traffic-light guide.
- Issue Register: ANALYSIS_REPORT.md updated with DONE / DEFERRED / SOURCE-LIMITED for every ID.

YOUR OBJECTIVE ON THIS SYSTEM:
1. Verify the local environment:
   - Check Python 3.11 environment (.venv-gate or .venv).
   - Ensure checkpoints best.pt, anpr_best.pt, weights/vehicle.pt are present.
   - Run: python -m pytest -q to verify the test suite.
   - Run: python desktop/gate/launcher.py --check to confirm preflight readiness.
2. Complete any pending deployment or live operational tasks requested by the user:
   - Run desktop/gate/launcher.py or desktop/gate/start_gate.bat to launch the portal.
   - Confirm web dashboard is reachable at http://127.0.0.1:8080.
   - If deploying as a Windows service or testing with an IP camera, configure CAMERA_SOURCE in %APPDATA%\VisionAI\gate.env.
3. Review docs/CONTINUATION_GUIDE.md and docs/RUNBOOK.md for full operational context.
```

---

## 2. Setup Instructions on New Machine

### Step 1: Clone Repository
```bash
git clone https://github.com/saran-44/VISION-AI-SRM-TRP.git
cd VISION-AI-SRM-TRP
git checkout main
```

### Step 2: Create Python Environment (Python 3.11 recommended)
```powershell
python -m venv --system-site-packages .venv-gate
.\.venv-gate\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### Step 3: Install Dependencies
```powershell
# Install CPU PyTorch wheels
pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu

# Install desktop requirements
pip install -r requirements-desktop.txt

# Install ultralytics without dependencies (to preserve single headless opencv)
pip install --no-deps ultralytics==8.4.20
```

### Step 4: Verify Models & Weights
Ensure the following files are in the repository:
- `best.pt` (Sticker detector, ~5.6 MB)
- `anpr_best.pt` (License plate detector, ~5.6 MB)
- `weights/vehicle.pt` (Vehicle classifier, ~5.5 MB; fetch with `python scripts/fetch_vehicle_model.py` if missing)

### Step 5: Run Verification
```powershell
# Run backend tests
python -m pytest -q

# Run gate preflight check
python desktop/gate/launcher.py --check

# Run the 5 gate acceptance checks
python scripts/gate_acceptance.py
```

### Step 6: Start the Application
- Run `desktop\gate\start_gate.bat`, or:
- Run `powershell -ExecutionPolicy Bypass -File desktop\gate\install_shortcut_and_task.ps1` to create desktop shortcut.

---

## 3. History of Remediation (Rounds 1 – 10)

| Round | Focus | Key Deliverables & Fixes |
| :--- | :--- | :--- |
| **Round 1** | Baseline Audit | Established test harness; identified sticker/plate cascade behavior and missing OCR ground truth. |
| **Round 2** | Stage Diagnostics | Diagnosed OCR skip condition (`not_needed`), analysed vehicle crop resolutions, fixed model paths. |
| **Round 3** | Cascade Fixes | Added `VISION_PLATE_MODE = fallback \| always`; isolated plate detection to vehicle crops instead of full 12 MP frames. |
| **Round 4** | Ground Truth | Restored manifest vehicle numbers; eliminated plate stage performance bottleneck through crop area ranking. |
| **Round 5** | Performance & Fallback | Bounded vehicle crops (`VISION_PLATE_MAX_CROPS=2`, min 200x200px); adaptive imgsz; Indian plate format validation. |
| **Round 6** | Accuracy & Timing | Strict candidate matching; orphan single-digit rejection ("89 9"); per-step timing breakdown profiling. |
| **Round 7** | CI & Environment | Fixed PostgreSQL 16 schema compatibility; resolved Linux CI CPU PyTorch wheel resolution; CI all green. |
| **Round 8** | Live Path & Replay | Live video replay with 8/8 buses verified; added `EVENT_DEBOUNCE_SECONDS`; dashboard webcam verdict strip (Light, Focus, Size). |
| **Round 9** | Windows Packaging | PyInstaller / Inno Setup build script; redirected state to `%APPDATA%\VisionAI`; single-instance focus; fallback batch runner & scheduled task. |
| **Round 10** | Handover | Ran 5 gate acceptance checks; verified CI conclusions; wrote `docs/RUNBOOK.md`; audited `ANALYSIS_REPORT.md` issue register. |

---

## 4. Scope Status (Delivered vs Non-Delivered)

### Delivered
- ✅ 12/12 bus numbers identified accurately across stills and video.
- ✅ 3/3 still license plates identified accurately.
- ✅ Full cascade architecture (Sticker -> Vehicle Crop -> Plate Crop -> Fallback OCR).
- ✅ Live event ingest with debounce duplicate suppression (`EVENT_DEBOUNCE_SECONDS`).
- ✅ Real-time webcam quality gate strip (Light / Focus / Size feedback).
- ✅ Clean Windows gate portal (`desktop/gate/start_gate.bat`, scheduled task, system tray, port collision handling).
- ✅ Complete operator runbook (`docs/RUNBOOK.md`).
- ✅ Green CI across Backend tests, Frontend checks, Secret scan, and Vision stack.

### Not Delivered (Plain Statement)
- ❌ **Full Video Number Plates (7/7)**: In `busvideo1.mp4`, vehicles are filmed at an oblique angle and distance at 25 fps. License plate bounding boxes average 18–35 px tall, well below the ~100–120 px needed for OCR legibility. Upscaling adds no high-frequency detail. This is **source-limited** by camera optics.
- ❌ **AGPL-3.0 Licensing Decision**: The YOLO models use Ultralytics code under AGPL-3.0. An engineering agent cannot make legal/licensing choices for the college. Documented in `docs/LICENSING_NOTE.md`.
- ❌ **Code Signing**: Binaries are unsigned because no institutional code signing certificate (.pfx/token) was provided.
