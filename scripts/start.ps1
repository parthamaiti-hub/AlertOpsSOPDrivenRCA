Set-Location (Split-Path $PSScriptRoot)
docker-compose up -d --build
Write-Host "Services started. App: http://localhost:8000  RabbitMQ: http://localhost:15672"
