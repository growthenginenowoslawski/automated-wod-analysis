# Automated WOD Analysis: one-time setup on Windows 10/11.
# Run in PowerShell from the repo folder:
#   powershell -ExecutionPolicy Bypass -File install\windows.ps1
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $PSScriptRoot
$WodHome = if ($env:WOD_HOME) { $env:WOD_HOME } else { Join-Path $HOME "WODs" }
$Inbox = if ($env:WOD_INBOX) { $env:WOD_INBOX } else { Join-Path $WodHome "inbox" }
$Venv = Join-Path $HOME ".wod-venv"
function Say($m) { Write-Host "`n$m" -ForegroundColor Cyan }

Say "1/4 Tools (ffmpeg, Python 3.12)"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}
$Py = $null
foreach ($v in "3.12", "3.11", "3.10") {
  try { & py "-$v" --version *> $null; if ($LASTEXITCODE -eq 0) { $Py = @("py", "-$v"); break } } catch {}
}
if (-not $Py) {
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  $Py = @("py", "-3.12")
}

Say "2/4 Installing the analyzer into $Venv"
& $Py[0] $Py[1] -m venv $Venv
& "$Venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install -q -e $Here
$Bin = Join-Path $HOME ".local\bin"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
Set-Content -Path (Join-Path $Bin "wod.cmd") -Value "@echo off`r`nset WOD_HOME=$WodHome`r`n`"$Venv\Scripts\wod.exe`" %*"
$UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$Bin*") { [System.Environment]::SetEnvironmentVariable("Path", "$UserPath;$Bin", "User") }
$env:Path += ";$Bin"

Say "3/4 Body-tracking model and data folder ($WodHome)"
$env:WOD_HOME = $WodHome
& "$Venv\Scripts\wod.exe" doctor --download

Say "4/4 Inbox watcher (starts when you log in; drop a video + its workout into $Inbox)"
New-Item -ItemType Directory -Force -Path $Inbox | Out-Null
$Action = New-ScheduledTaskAction -Execute "$Venv\Scripts\wod.exe" -Argument "watch --inbox `"$Inbox`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "AutomatedWODAnalysis" -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName "AutomatedWODAnalysis"

Say "Done. Open a new PowerShell window, then:"
Write-Host "  wod analyze $HOME\Downloads\IMG_1234.MOV --workout examples\amrap.txt"
Write-Host "  wod stats   ·   wod dashboard   ·   wod summary"
Write-Host "  Using Claude Code: copy skills\automated-wod-analysis to $HOME\.claude\skills\"
