FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data

EXPOSE 8080

# 默认启动 Web 看板（常驻）；如需纯定时扫描可改为 scripts/daily_scan.py
CMD ["python", "-m", "src.server"]
