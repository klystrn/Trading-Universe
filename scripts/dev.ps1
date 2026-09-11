# Start Trading Universe locally on Windows: backend in a new window, frontend here.
# Usage (from the repo root):  .\scripts\dev.ps1
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env" }
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; python -m trading_universe.cli serve"
Set-Location "$root\frontend"
if (-not (Test-Path "node_modules")) { npm install }
npm run dev
