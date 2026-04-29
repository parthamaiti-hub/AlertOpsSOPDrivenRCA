#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
docker compose up -d --build
echo "Services started. App: http://localhost:8000  RabbitMQ: http://localhost:15672"
