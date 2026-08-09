#!/bin/bash
# Local Execution Script for AI Autonomous Developer (uv + Clean Architecture)

if [ -f .env ]; then
  echo "🔑 Loading environment variables from .env file..."
  export $(grep -v '^#' .env | xargs)
else
  echo "⚠️ .env file not found! Please copy .env.example to .env and set your keys."
  exit 1
fi

if [ -z "$GEMINI_API_KEY" ] || [ -z "$GITHUB_TOKEN" ] || [ -z "$GITHUB_REPOSITORY" ]; then
  echo "❌ Missing required environment variables! Ensure GEMINI_API_KEY, GITHUB_TOKEN, and GITHUB_REPOSITORY are set in .env"
  exit 1
fi

echo "🚀 Running AI Developer script locally via uv..."
uv run main.py
