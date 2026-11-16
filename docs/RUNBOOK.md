# Gate Operator Runbook — VISION AI - SRM TRP

A practical guide for gate security staff and operators running the vehicle entry and exit system.

---

## 1. How to Start the App

1. Double-click the **Vision AI Gate Portal** icon on your Desktop.
   *(Alternatively, double-click `desktop\gate\start_gate.bat`).*
2. The system will start automatically, open your default web browser to **`http://127.0.0.1:8080`**, and place an icon in your Windows system tray (bottom-right near the clock).
3. If the browser does not open automatically, open Google Chrome or Edge and navigate to:
   `http://localhost:8080`
4. If the app is already open, clicking the shortcut simply brings the running window to the front.

---

## 2. What the Three Camera Lights Mean

At the top of the live camera feed, you will see three status lights: **Light**, **Focus**, and **Size**.

| Indicator | Metric | What it checks |
| :--- | :--- | :--- |
| **Light** | Brightness | Ensures the vehicle front and sticker are clearly visible, not pitch black or blinded by glare. |
| **Focus** | Sharpness | Ensures the image is crisp and not blurry from high speed or an unfocused lens. |
| **Size** | Crop Dimensions | Ensures the vehicle is close enough to read the bus sticker number accurately. |

---

## 3. What to Do for Each Colour

### 🟢 Green — Ready / Good
- Everything looks great. The system will detect stickers and read bus numbers automatically.

### 🟡 Amber — Borderline
- **Amber Light**: Lighting is a bit dim. The camera might still read the sticker, but consider turning on the gate overhead light or floodlight.
- **Amber Focus**: Slight blur. Ask the driver to pause briefly at the white stop line.
- **Amber Size**: The vehicle is slightly far back. Ask the driver to pull forward 1 to 2 meters.

### 🔴 Red — Scan Blocked / Action Required
- **Red Light ("The camera returned a black frame / too dark")**:
  - The camera lens cap may be on, the cable disconnected, or the area is pitch black.
  - Turn on the gate light, ensure infrared/night vision is active, or check the camera connection.
- **Red Focus ("Too blurry")**:
  - The vehicle moved too quickly through the gate or rain/dirt is on the camera lens.
  - Wipe the lens clean with a cloth, and ask the driver to stop at the gate line.
- **Red Size ("Too small / too far")**:
  - The bus is parked too far away (sticker is smaller than 45 pixels).
  - Have the bus drive up to the designated scanning line so the front windshield fills the camera view.

---

## 4. How to Read `--report` (System Diagnostics)

If something isn't working and technical support asks for a diagnostic report:
1. Open a terminal or PowerShell in the application folder and run:
   ```cmd
   python desktop\gate\launcher.py --report
   ```
2. The screen displays a clear summary of system health:
   - **Configuration**: Shows your active port, gate name, and database status.
   - **Vision Stack**: Confirms whether the AI models (`best.pt`, `anpr_best.pt`, `vehicle.pt`) are loaded and whether OCR is active.
   - **Preflight Checks**: Lists green `PASS` checks or red `FAIL` warnings.
   - **Recent Errors**: Shows any recent camera drops or unreadable scans with timestamps.
3. A copy of the report is automatically saved to:
   `%APPDATA%\VisionAI\logs\report.txt`
   You can attach this file directly in an email to technical support.

---

## 5. How to Reinstall or Reset

If the application files become corrupted or you need to set up on a new PC:
1. Ensure Python 3.11 is installed on the computer.
2. In the `VISION-AI-SRM-TRP` folder, open PowerShell as Administrator and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File desktop\gate\install_shortcut_and_task.ps1
   ```
3. Run the initial configuration wizard:
   ```cmd
   python desktop\gate\launcher.py --setup
   ```
   Follow the on-screen prompts to set your administrator password and camera source.
4. Verify with the preflight check:
   ```cmd
   python desktop\gate\launcher.py --check
   ```
   When it displays `READY: 0 failed`, setup is complete.

---

## 6. Who to Call for Support

- **SRM TRP Transport Desk**: Ext. 104 / Intercom Gate 1
- **Campus IT / Systems Admin**: `admin@trp.srmtrichy.edu.in`
- **Lead Developer / Engineering Team**: Reachable via project issue tracker or local IT escalation.
