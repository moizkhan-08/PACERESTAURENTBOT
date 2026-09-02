#!/bin/bash

# Pace Restaurant AI Agent — Automatic Deployment Script

echo "🚀🔥 Starting automatic deployment..."

# 1. Pull latest changes from GitHub
echo "📥 Pulling latest changes from GitHub..."
git pull origin main

# 2. Build and restart containers
echo "🏗️ Rebuilding and restarting Docker containers..."
docker compose up -d --build

# 3. Cleanup old images
echo "🧹 Cleaning up unused Docker images..."
docker image prune -f

echo "✅ Deployment complete! Pace Bot is running."
