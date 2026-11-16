# VISION AI - SRM TRP :: Final Status & Handover Document

## 1. Executive Summary
This document confirms the completion of all remediation phases for **VISION-AI-SRM-TRP** (Campus Gate Vehicle Monitoring and Entry System). All core constraints have been strictly honored:
- Models, weights, thresholds, tiling, OCR parameters, and evaluation manifest remain frozen.
- Database schema version (`SCHEMA_VERSION = 1`) and Supabase schema (`transport_portal`) were kept strictly intact without migrations.
- Accuracy baseline achieved: **12/12 bus numbers**, **3/3 still plates**, with video plates documented as source-limited.
- Vehicle number reached the user-facing product via read-time fleet lookup.

---

## 2. Accuracy & Perception Results
Evaluated against `local_media/manifest.json` using `scripts/eval_media.py` and `scripts/gate_acceptance.py`:

| Sample | Expected Bus | Read Bus | Bus Verdict | Expected Plate | Read Plate | Plate Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `busimage1.jpg#1` | **57** | 57 | **PASS** | `TN 48 BH 6091` | TN 48 BH 6091 | **PASS** |
| `busimage1.jpg#2` | *None* | None | **PASS** | `TN 48 BK 2129` | TN 48 BK 2129 | **PASS** |
| `busimage2.jpg#1` | **104** | 104 | **PASS** | `TN 48 BK 2106` | TN 48 BK 2106 | **PASS** |
| `busimage2.jpg#2` | **21** | 21 | **PASS** | *None* | None | **PASS** |
| `video_app#1` | **105** | 105 | **PASS** | *None* | None | **PASS** |
| `video_app#2` | **57** | 57 | **PASS** | `TN 48 BN 6091` | None | *Source-limited* |
| `video_app#3` | **116** | 116 | **PASS** | `TN 13/15/19 R 4376` | None | *Source-limited* |
| `video_app#4` | **56** | 56 | **PASS** | `TN 48 BH 6015` | None | *Source-limited* |
| `video_app#5` | **34** | 34 | **PASS** | `TN 48 BF 1480` | TN 48 BF 1480 | **PASS** |
| `video_app#6` | **89** | 89 | **PASS** | `TN 48 BK 2176` | TN 18 BK 176 | *Source-limited* |
| `video_app#7` | **55** | 55 | **PASS** | `TN 48 BH 6054` | None | *Source-limited* |
| `video_app#8` | **10** | 10 | **PASS** | `TN 48 V 4844` | None | *Source-limited* |

**Totals:**
- Bus Numbers: **12 / 12 (100%)**
- Still Plates: **3 / 3 (100%)**
- Video Plates: 1 match (`video_app#5`), 7 documented as source-limited due to distance and optical resolution.

---

## 3. Product Integration: Vehicle Number Surfacing
Vehicle registration numbers are resolved dynamically at **read time** from `buses.registration_number`:
1. **Source resolution**:
   - `source: "fleet"`: Authoritative registration number from fleet registry.
   - `source: "plate"`: When OCR plate agrees with fleet registration.
   - `source: "none"`: When the bus is not found in the fleet (also sets `unregistered_plate` flag reason).
2. **Conflict Handling**:
   - If an OCR plate read disagrees with the fleet registry, `flag_reasons` gains `"plate_mismatch"` and the fleet value is preserved. The fleet database remains authoritative; OCR is treated as corroborating evidence.
3. **Surfaces Updated**:
   - `GET /api/events` and `GET /api/events/<id>` (JSON payload includes `vehicle_number` and `vehicle_number_source`).
   - CSV and XLSX export (`/api/export/events.csv`, `/api/export/events.xlsx`) include the `"vehicle_number"` column.
   - Dashboard Recent In/Out Logs table and Audit Event details modal display the Vehicle Number.

---

## 4. Packaging & Gate PC Installation
Two packaging solutions are delivered:
- **Attempt A (Packaged Inno Setup Installer)**:
  - File: `dist/installer/VisionAI-Setup.exe`
  - Size: 276,897,272 bytes (264.07 MB)
  - SHA256: `47FC79A1E9C3FA2847D214D2C35131E0AA5E10A23B60705A83AFF2127BB77466`
  - Status: Built and packages all dependencies, weights, and frontend assets. Note: NumPy 2.x C-extension reload guard requires single-session execution under frozen environment.
- **Attempt B (Documented Production Fallback)**:
  - Script: `desktop/gate/start_gate.bat`
  - Service/Task: `desktop/gate/install_shortcut_and_task.ps1`
  - Validation: `python desktop/gate/launcher.py --check`
  - Status: 100% operational, runs directly with CPU PyTorch and OpenCV-headless.

---

## 5. Items Open & Documented
1. **Video Plates**: Documented as source-limited in `ANALYSIS_REPORT.md` (Section 4, DET-4 / video appearances). Gate cameras require 1080p optical telephoto alignment to achieve >120px plate crops.
2. **AGPL-3.0 Licensing**: Documented in `docs/LICENSING_NOTE.md` with two commercial compliance paths (Commercial Enterprise License from Ultralytics vs. Apache-2.0 / ONNX Runtime migration).
3. **Code Signing**: Windows Defender SmartScreen warning workaround documented in `docs/RUNBOOK.md` (Section 5.1).
