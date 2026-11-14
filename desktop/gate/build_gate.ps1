# Build VisionAI.exe on Windows. Run from the repository root in PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File desktop\gate\build_gate.ps1
#
# Produces dist\VisionAI\VisionAI.exe (portable) and, if Inno Setup is
# installed, dist\installer\VisionAI-Setup.exe.
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

$Venv = Join-Path $RepoRoot ".venv-gate"
$Python = Join-Path $Venv "Scripts\python.exe"

Write-Host "== 1/6  Python environment ==" -ForegroundColor Cyan
if (-not (Test-Path $Python)) {
    python -m venv $Venv
}
& $Python -m pip install --upgrade pip --quiet
# CPU torch first: the default wheel drags in ~3 GB of CUDA libraries a gate PC
# cannot use, and it makes the bundle four times larger for no benefit.
& $Python -m pip install --quiet torch==2.9.1 torchvision==0.24.1 `
    --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw "torch install failed" }
& $Python -m pip install --quiet -r requirements-desktop.txt
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

Write-Host "== 2/6  Checkpoints ==" -ForegroundColor Cyan
foreach ($model in @("best.pt", "anpr_best.pt")) {
    if (-not (Test-Path (Join-Path $RepoRoot $model))) { throw "$model is missing from the repository root" }
}
if (-not (Test-Path (Join-Path $RepoRoot "weights\vehicle.pt"))) {
    & $Python scripts\fetch_vehicle_model.py
    if ($LASTEXITCODE -ne 0) { Write-Warning "vehicle.pt was not fetched; the vehicle stage will be skipped" }
}

Write-Host "== 3/6  Source tests (fail fast, before a 15-minute build) ==" -ForegroundColor Cyan
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "the test suite is not green: fix that before packaging" }

Write-Host "== 4/6  Building dist\VisionAI ==" -ForegroundColor Cyan
& $Python -m PyInstaller --noconfirm --clean desktop\gate\VisionAI.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$Exe = Join-Path $RepoRoot "dist\VisionAI\VisionAI.exe"
if (-not (Test-Path $Exe)) { throw "VisionAI.exe was not produced" }
$SizeMb = [math]::Round(((Get-ChildItem -Recurse (Split-Path $Exe) | Measure-Object -Property Length -Sum).Sum / 1MB), 0)
Write-Host "   bundle: $SizeMb MB" -ForegroundColor Green

Write-Host "== 5/6  Smoke test: does the built executable actually run? ==" -ForegroundColor Cyan
# A throwaway data folder, so the build machine's real gate configuration and
# database are never touched by a test.
$Smoke = Join-Path $env:TEMP ("visionai-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $Smoke -Force | Out-Null
# A port in the dynamic range: 8080 may already be taken on a build machine,
# and the launcher would then pick 8081 while this script polls 8080.
$SmokePort = Get-Random -Minimum 18080 -Maximum 18999
$env:PORT = "$SmokePort"
$env:VISION_DATA_DIR = $Smoke
$env:ENVIRONMENT = "gate"
$env:DATABASE_URL = "sqlite:///$($Smoke.Replace('\','/'))/smoke.db"
$env:JWT_SECRET = "smoke-test-secret-" + ("x" * 32)
$env:LEGACY_PASSWORD_LOGIN_ENABLED = "true"
$env:FIREBASE_AUTH_ENABLED = "false"
$env:DEMO_MODE = "false"
$env:COOKIE_SECURE = "false"
$env:RATELIMIT_ENABLED = "false"

$Check = & $Exe --check --json 2>&1 | Out-String
if ($Check -notmatch '"ready"') { throw "the bundled preflight did not run:`n$Check" }
Write-Host "   preflight ran inside the bundle" -ForegroundColor Green

# The server has to answer /api/health, not merely start.
$Proc = Start-Process -FilePath $Exe -ArgumentList "--no-browser", "--no-tray", "--host", "127.0.0.1" -PassThru
$healthy = $false
foreach ($attempt in 1..40) {
    Start-Sleep -Milliseconds 750
    try {
        $reply = Invoke-RestMethod -Uri "http://127.0.0.1:$SmokePort/api/health" -TimeoutSec 2
        if ($reply.service -eq "srm-trp-transport") { $healthy = $true; break }
    } catch { }
    if ($Proc.HasExited) { break }
}
if (-not $healthy) {
    if (-not $Proc.HasExited) { Stop-Process -Id $Proc.Id -Force }
    throw "the built portal did not answer /api/health; see $Smoke\logs\portal.log"
}
$index = Invoke-WebRequest -Uri "http://127.0.0.1:$SmokePort/" -TimeoutSec 5
Write-Host "   portal answered: health ok, index $($index.StatusCode) ($($index.RawContentLength) bytes)" -ForegroundColor Green
Stop-Process -Id $Proc.Id -Force
Remove-Item -Recurse -Force $Smoke -ErrorAction SilentlyContinue
Remove-Item Env:VISION_DATA_DIR, Env:PORT, Env:ENVIRONMENT, Env:DATABASE_URL, Env:JWT_SECRET, `
    Env:LEGACY_PASSWORD_LOGIN_ENABLED, Env:FIREBASE_AUTH_ENABLED, Env:DEMO_MODE, `
    Env:COOKIE_SECURE, Env:RATELIMIT_ENABLED -ErrorAction SilentlyContinue

Write-Host "== 6/6  Installer ==" -ForegroundColor Cyan
$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($Iscc) {
    & $Iscc "desktop\gate\VisionAI.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    Write-Host "   installer: dist\installer\VisionAI-Setup.exe" -ForegroundColor Green
} else {
    Write-Warning "Inno Setup 6 is not installed; the portable folder is ready: dist\VisionAI"
    Write-Warning "Install it (winget install --id JRSoftware.InnoSetup) and re-run, or copy dist\VisionAI to the gate PC as-is."
}

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "  portable : dist\VisionAI\VisionAI.exe"
if ($Iscc) { Write-Host "  installer: dist\installer\VisionAI-Setup.exe" }
Write-Host ""
Write-Host "On the gate PC: VisionAI.exe --setup   then   VisionAI.exe --check"
