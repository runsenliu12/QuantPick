#!/usr/bin/env bash
# QuantPick 一键部署/管理（Docker）
set -e

case "$1" in
  stop)    docker compose down ;;
  restart) docker compose restart ;;
  logs)    docker compose logs -f ;;
  status)  docker compose ps ;;
  rebuild) docker compose up -d --build ;;
  *)       docker compose up -d --build ;;
esac
