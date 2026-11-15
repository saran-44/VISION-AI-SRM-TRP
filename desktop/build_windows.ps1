# Superseded. This script built a second, older agent called
# "VisionAI-GateAgent" from desktop/detector_agent.py, with a different config
# folder (%APPDATA%\VisionAI\GateAgent) and without the gate setup wizard,
# `--check` or `--report`. Shipped builds are produced by the script below,
# which is why `/api/detection/scan` on a cloud instance tells operators to run
# VisionAI.exe and why nothing anywhere should mention GateAgent.
#
# Kept only so an old shortcut or a wiki page does not fail with "file not
# found": it forwards to the supported build.
$ErrorActionPreference = "Stop"

Write-Host "desktop\build_windows.ps1 is superseded - building VisionAI.exe instead."
Write-Host "The supported entry point is: desktop\gate\build_gate.ps1"
Write-Host ""

& (Join-Path $PSScriptRoot "gate\build_gate.ps1") @args
exit $LASTEXITCODE
