#!/usr/bin/env bash
set -euo pipefail

echo "Stopping all services..."
docker compose -f docker/docker-compose.yml down
echo "All services stopped."
