# 𐌽ꤕ𐌗ተ — образ для запуска на любом сервере с Docker
FROM python:3.12-slim

# Не писать .pyc, не буферизировать stdout (логи сразу видны)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала зависимости — для кэширования слоёв
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код
COPY . .

# Keep-alive HTTP-сервер (для хостингов, которым нужен открытый порт)
EXPOSE 8080

CMD ["python", "main.py"]
