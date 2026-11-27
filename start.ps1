# Build the web UI, then start SubStudio on http://<this-machine>:8000
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Always rebuild: web\dist is git-ignored, so an existing one can be older than the pulled source.
Push-Location web
if (-not (Test-Path "node_modules")) { npm install }
npm run build
Pop-Location

& "backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
