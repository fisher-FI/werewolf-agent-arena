#!/bin/bash
# AI 狼人杀 — 一键启动脚本
set -e
cd "$(dirname "$0")"

# 加载环境变量
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "🐺 AI 狼人杀 启动中..."

# 启动后端
echo "📦 启动后端 (FastAPI)..."
cd backend
pip install -q -r requirements.txt 2>/dev/null
cd ..

# 构建前端（如果 static 目录不存在）
if [ ! -d "backend/static/assets" ]; then
  echo "🔨 构建前端..."
  cd frontend
  npm install -q 2>/dev/null
  npm run build
  cd ..
fi

echo "🚀 启动服务 http://localhost:8822"
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8822 --reload
