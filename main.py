# main.py (UI-Bot)
import os
import asyncio
import logging
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Наши модули
from user_db_handler import init_db, save_encrypted_credentials, get_encrypted_data_from_local_db
from crypto_utils import encrypt_data
# Импорт Supabase (для чтения user_signals и записи signal_requests)
from supabase import create_client, Client
from dotenv import load_dotenv

# --- Настройка ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Переменные окружения для Supabase и Telegram
TELEGRAM_BOT_TOKEN_UI = os.getenv("TELEGRAM_BOT_TOKEN_UI")
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
SUPABASE_KEY = os.getenv("SUPABASE_KEY_FOR_CORE") # Используем публичный ключ для чтения

# Инициализация Supabase
supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY)
# Инициализация локальной БД
init_db()

# --- 1. FastAPI API-сервер (Связь с Ядром Render) ---
api_app = FastAPI(title="UI Bot API for Trading Core")

# Модель данных для входящего запроса от Ядра Render
class CoreRequest(BaseModel):
    user_id: int
    request_source: str

@api_app.post("/get_po_credentials")
async def get_po_credentials_endpoint(request_data: CoreRequest):
    """
    Эндпоинт, который Ядро Render использует для получения зашифрованных данных PO.
    """
    user_id = request_data.user_id
    
    # Здесь можно добавить проверку секретного ключа/токена для защиты

    try:
        encrypted_creds = await get_encrypted_data_from_local_db(user_id) 
        
        if not encrypted_creds:
            raise HTTPException(status_code=404, detail=f"Credentials not found for user {user_id}")
            
        return {
            "status": "success",
            "user_id": user_id,
            "login_enc": encrypted_creds['login_enc'],
            "password_enc": encrypted_creds['password_enc']
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"❌ DB Error for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal database error")


# --- 2. Telegram Bot Логика (Пользовательский интерфейс) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start."""
    await update.message.reply_text(
        "👋 Добро пожаловать! Я — Ваш торговый бот. Используйте /set_po для настройки Pocket Option или /signal для запроса сигнала."
    )

async def set_po_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Начинает процесс сохранения учетных данных PO."""
    # Пример простой обработки
    if context.args and len(context.args) == 2:
        login = context.args[0]
        password = context.args[1]
        user_id = update.effective_user.id
        
        # 1. Шифрование
        login_enc = encrypt_data(login)
        password_enc = encrypt_data(password)
        
        if not login_enc or not password_enc:
             await update.message.reply_text("❌ Ошибка шифрования. Проверьте ENCRYPTION_KEY в .env")
             return

        # 2. Сохранение в локальной БД (только зашифрованные данные)
        await save_encrypted_credentials(user_id, login_enc, password_enc)
        
        await update.message.reply_text("✅ Ваши данные Pocket Option зашифрованы и сохранены локально.")
    else:
        await update.message.reply_text("Использование: /set_po [логин] [пароль]. *Не используйте реальные данные пока не убедитесь в безопасности!*")


async def request_signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /signal (запрос к Ядру Render через Supabase)."""
    user_id = update.effective_user.id
    
    try:
        # Запись запроса в таблицу signal_requests (Supabase)
        supabase.table("signal_requests").insert({
            'user_id': user_id,
            'request_type': 'latest_signal',
            'status': 'pending',
            'created_at': 'now()'
        }).execute()
        
        await update.message.reply_text(
            "⏳ Запрос на сигнал отправлен. Ядро Анализа (Render) обработает его в ближайшее время и пришлет ответ."
        )
        
    except Exception as e:
        logger.error(f"❌ Supabase error: {e}")
        await update.message.reply_text("❌ Ошибка при отправке запроса в базу данных.")


def run_telegram_bot():
    """Запускает Telegram-бот."""
    if not TELEGRAM_BOT_TOKEN_UI:
        logger.error("🚫 TELEGRAM_BOT_TOKEN_UI не задан. Бот не будет запущен.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN_UI).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("set_po", set_po_command))
    application.add_handler(CommandHandler("signal", request_signal_command))
    
    # Запуск бота (без блокировки)
    application.run_polling(poll_interval=1.0, timeout=10, drop_pending_updates=True, stop_on_shutdown=False)


# --- 3. Объединение и Запуск ---

async def main():
    """Главная асинхронная функция, запускающая оба процесса."""
    logger.info("🚀 Запуск UI-Бота (Telegram + API Server)...")

    # 1. Запуск Telegram Bot в отдельном потоке
    telegram_task = asyncio.to_thread(run_telegram_bot)
    
    # 2. Настройка и запуск FastAPI (uvicorn)
    # При деплое на Bothost, порт может быть задан хостингом (обычно PORT=8000)
    config = uvicorn.Config(api_app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")
    server = uvicorn.Server(config)
    
    api_task = asyncio.create_task(server.serve())

    # Ждем, пока оба процесса работают
    await asyncio.gather(telegram_task, api_task)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Оба процесса остановлены.")
