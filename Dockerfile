FROM python:3.13-slim

WORKDIR /app

# 健康检查依赖 curl
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data

EXPOSE 8080

# 容器健康检查：探测 Web 看板健康端点
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# 默认启动 Web 看板（常驻）；如需纯定时扫描可改为 scripts/daily_scan.py
CMD ["python", "-m", "src.server"]
