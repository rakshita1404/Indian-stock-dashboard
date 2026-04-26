Set-Location -Path $PSScriptRoot
Write-Host "Starting StockDesk at http://127.0.0.1:8000"
Write-Host "Keep this PowerShell window open while using the dashboard."
Write-Host ""
python app.py
