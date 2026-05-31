#!/usr/bin/env bash
# scripts/setup.sh — First-time setup for DevMentor AI
set -euo pipefail

echo "🛠️  DevMentor AI — First-time setup"

command -v docker >/dev/null 2>&1 || { echo "❌ Docker not installed. See https://docs.docker.com/get-docker/"; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
  if [ "$(uname)" = "Darwin" ]; then
    sed -i '' "s/your-super-secret-key-change-this-in-production/$SECRET/" .env
  else
    sed -i "s/your-super-secret-key-change-this-in-production/$SECRET/" .env
  fi
  echo "✅ Created .env with a generated SECRET_KEY"
  echo ""
  echo "⚠️  Set your GROQ_API_KEY in .env before continuing."
  echo "   Free key: https://console.groq.com"
  echo ""
  read -p "Press Enter once GROQ_API_KEY is set in .env..."
fi

echo "🐳 Building Docker images (first run: ~5 minutes)..."
docker compose build

echo "🗄️  Starting database..."
docker compose up -d postgres redis
until docker compose exec -T postgres pg_isready -U devmentor -d devmentor 2>/dev/null; do sleep 2; done

echo "🔄 Running database migrations..."
docker compose run --rm backend alembic upgrade head

echo "🚀 Starting all services..."
docker compose up -d

echo ""
echo "✅ Done! DevMentor AI is running at http://localhost"
echo "   Register at http://localhost/register"
echo "   API docs   at http://localhost/docs"
