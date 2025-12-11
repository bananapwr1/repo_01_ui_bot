FROM python:3.11-slim

WORKDIR /app

# Устанавливаем зависимости в правильном порядке
COPY requirements.txt .
RUN pip install --no-cache-dir \
    httpx==0.24.0 \
    python-telegram-bot==20.3 \
    python-dotenv==1.0.0 \
    supabase>=2.0.0

# Копируем код
COPY . .

# Запускаем бота
CMD ["python", "main.py"]