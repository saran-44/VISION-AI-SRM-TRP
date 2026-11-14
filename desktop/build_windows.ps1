$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)
python -m pip install -r requirements-desktop.txt `
  --extra-index-url https://download.pytorch.org/whl/cpu

if (-not (Test-Path "weights\vehicle.pt")) {
    python scripts\fetch_vehicle_model.py
}

python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name "VisionAI-GateAgent" `
  --collect-all ultralytics `
  --collect-all rapidocr_onnxruntime `
  --collect-all onnxruntime `
  --collect-all torch `
  --add-data "best.pt;." `
  --add-data "anpr_best.pt;." `
  --add-data "weights\vehicle.pt;weights" `
  desktop\detector_agent.py

Write-Host "Build complete: dist\VisionAI-GateAgent\VisionAI-GateAgent.exe"
