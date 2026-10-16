# Automated WOD Analysis: setup for Windows 10/11. No admin rights needed.
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/growthenginenowoslawski/automated-wod-analysis/main/install/windows.ps1 | iex"
$ErrorActionPreference = "Stop"
$Src = if ($env:WOD_SOURCE) { $env:WOD_SOURCE } else { "https://github.com/growthenginenowoslawski/automated-wod-analysis/archive/refs/heads/main.zip" }
$Uv = Join-Path $HOME ".local\bin\uv.exe"

Write-Host "1/3 Installing uv (a small tool that brings its own Python)..."
if (-not (Get-Command uv -ErrorAction SilentlyContinue) -and -not (Test-Path $Uv)) {
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
}
if (Get-Command uv -ErrorAction SilentlyContinue) { $Uv = (Get-Command uv).Source }

Write-Host "2/3 Installing Automated WOD Analysis..."
& $Uv tool install --force --python 3.12 "automated-wod-analysis @ $Src"

& $Uv tool update-shell *> $null   # so new PowerShell windows find `wod`

Write-Host "3/3 Setting up (model, folders, assistant instructions, inbox watcher)..."
& (Join-Path $HOME ".local\bin\wod.exe") setup

Write-Host ""
Write-Host "Done. Open a new PowerShell window and type: wod doctor"
