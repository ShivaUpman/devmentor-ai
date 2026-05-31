#!/usr/bin/env bash
# scripts/deploy.sh — Zero-downtime deployment
set -euo pipefail

echo "🚀 Deploying DevMentor AI..."

docker compose pull backend ml
docker compose exec -T backend alembic upgrade head
docker compose up -d --no-deps backend ml frontend nginx

for i in $(seq 1 10); do
  curl -sf http://localhost/health > /dev/null 2>&1 && echo "✅ Deployed successfully!" && exit 0
  echo "   Health check $i/10..."
  sleep 3
done

echo "❌ Health check failed. Check: docker compose logs backend"
exit 1
