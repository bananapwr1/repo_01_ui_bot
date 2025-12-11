import os
import json
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional

# Локальные модули
# Здесь будет функция для чтения из локальной БД Bothost
from user_db_handler import get_encrypted_data_from_local_db 
# from crypto_utils import decrypt_data # НЕ НУЖНО! Отдаем зашифрованные данные

# --- Настройка FastAPI ---
app = FastAPI()

# Ключ для защиты API (должен совпадать с тем, что в autotrader_service.py)
# ВРЕМЕННО: Для дебага мы его пока не используем, но его нужно добавить для продакшена!
# CORE_SECRET_KEY = os.getenv("CORE_SECRET_KEY") 

# Модель данных для входящего запроса от Ядра Render
class CoreRequest(BaseModel):
    user_id: int
    request_source: str # Дополнительная проверка, что запрос от Ядра Render

@app.post("/get_po_credentials", response_model=Dict[str, Any])
async def get_po_credentials_endpoint(request_data: CoreRequest):
    """
    Эндпоинт, который Ядро Render использует для получения 
    зашифрованных логинов/паролей PO по user_id.
    """
    user_id = request_data.user_id
    
    # --- 1. Проверка Защиты (Обязательно для Продакшена) ---
    # if request.headers.get("Authorization") != f"Bearer {CORE_SECRET_KEY}":
    #     raise HTTPException(status_code=403, detail="Forbidden: Invalid core key")

    # --- 2. Чтение из Локальной БД Bothost ---
    # Предполагается, что get_encrypted_data_from_local_db возвращает {login_enc, password_enc}
    try:
        encrypted_creds = await get_encrypted_data_from_local_db(user_id) 
        
        if not encrypted_creds:
            raise HTTPException(status_code=404, detail=f"Credentials not found for user {user_id}")
            
        # --- 3. Возврат Зашифрованных Данных ---
        return {
            "status": "success",
            "user_id": user_id,
            "login_enc": encrypted_creds['login_enc'],
            "password_enc": encrypted_creds['password_enc']
        }

    except HTTPException as e:
        raise e # Пробрасываем ошибку 404
    except Exception as e:
        # Логгирование ошибки базы данных
        print(f"Error accessing local DB for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal database error")


# --- Запуск API-сервера ---
# При деплое на Bothost, нужно использовать uvicorn/gunicorn для запуска FastAPI.
# Bothost должен быть настроен так, чтобы он мог слушать внешний порт (Web App).
# Для локального тестирования: uvicorn api_server:app --host 0.0.0.0 --port 8000
