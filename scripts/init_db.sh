#!/usr/bin/env bash
set -euo pipefail

echo "Starting Postgres + TimescaleDB..."
docker-compose up -d

echo "Waiting for healthy..."
until docker-compose exec -T db pg_isready -U fflow -d fflow; do
  sleep 2
done

echo "Running fflow db init..."
uv run fflow db init

echo "Running alembic upgrade head..."
uv run alembic upgrade head

echo "Done. Database is ready."
