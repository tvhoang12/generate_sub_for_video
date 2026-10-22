# Build the web UI if needed, then start SubStudio on http://<this-machine>:8000
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "web\dist\index.html")) {
    Push-Location web
    npm install
    npm run build
    Pop-Location
}

& "backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
