# Create desktop shortcut and Windows Scheduled Task to start VisionAI at login/boot.
# Run in PowerShell (Admin recommended for scheduled task):
#   powershell -ExecutionPolicy Bypass -File desktop\gate\install_shortcut_and_task.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BatPath = Join-Path $RepoRoot "desktop\gate\start_gate.bat"

if (-not (Test-Path $BatPath)) {
    throw "start_gate.bat not found at $BatPath"
}

Write-Host "== Creating Desktop Shortcut ==" -ForegroundColor Cyan
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "Vision AI Gate Portal.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $BatPath
$Shortcut.WorkingDirectory = $RepoRoot
$Shortcut.Description = "Launch VISION AI - SRM TRP Gate Portal"
$Shortcut.Save()
Write-Host "Created shortcut: $ShortcutPath" -ForegroundColor Green

Write-Host "`n== Registering Windows Scheduled Task (Boot/Logon) ==" -ForegroundColor Cyan
$TaskName = "VisionAI_GatePortal"
try {
    $Action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $RepoRoot
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Auto-start VISION AI Gate Portal at Logon" -Force | Out-Null
    Write-Host "Registered scheduled task: $TaskName" -ForegroundColor Green
} catch {
    Write-Warning "Could not register scheduled task: $_. Run PowerShell as Administrator to enable auto-start on boot."
}

Write-Host "`nSetup complete. Double-click the desktop shortcut to start VisionAI." -ForegroundColor Green
