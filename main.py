# main.py (UI-Bot)
import os
import asyncio
import logging
import uvicorn
from typing import Optional
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
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")

# Проверка наличия обязательных переменных
if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("🚫 SUPABASE_URL или SUPABASE_KEY не установлены!")
    raise ValueError("Необходимо установить переменные окружения SUPABASE_URL и NEXT_PUBLIC_SUPABASE_ANON_KEY")

# Инициализация Supabase
supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY)
# Инициализация локальной БД
init_db()

# --- 1. FastAPI API-сервер (Связь с Ядром Render) ---
api_app = FastAPI(
    title="UI Bot API for Trading Core",
    description="API для связи UI-бота с Ядром Анализа",
    version="1.0.0"
)

# Модель данных для входящего запроса от Ядра Render
class CoreRequest(BaseModel):
    user_id: int
    request_source: str

@api_app.get("/")
async def root():
    """Корневой эндпоинт - healthcheck."""
    return {
        "status": "ok",
        "service": "UI Bot API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "credentials": "/get_po_credentials"
        }
    }

@api_app.get("/health")
async def health_check():
    """Проверка здоровья сервиса."""
    try:
        # Проверка подключения к Supabase
        supabase.table("signal_requests").select("id").limit(1).execute()
        supabase_status = "connected"
    except Exception as e:
        logger.error(f"Supabase health check failed: {e}")
        supabase_status = "disconnected"
    
    return {
        "status": "healthy",
        "telegram_bot": "configured" if TELEGRAM_BOT_TOKEN_UI else "not_configured",
        "supabase": supabase_status,
        "encryption": "enabled"
    }

@api_app.post("/get_po_credentials")
async def get_po_credentials_endpoint(request_data: CoreRequest):
    """
    Эндпоинт, который Ядро Render использует для получения зашифрованных данных PO.
    
    Args:
        request_data: Запрос с user_id и source
        
    Returns:
        Зашифрованные учетные данные пользователя
    """
    user_id = request_data.user_id
    request_source = request_data.request_source
    
    logger.info(f"📥 Credential request for user {user_id} from {request_source}")
    
    # Базовая проверка источника запроса
    if request_source not in ["trading_core", "render_core", "admin"]:
        logger.warning(f"⚠️ Unknown request source: {request_source}")
        raise HTTPException(status_code=403, detail="Unknown request source")

    try:
        encrypted_creds = await get_encrypted_data_from_local_db(user_id) 
        
        if not encrypted_creds:
            logger.warning(f"⚠️ Credentials not found for user {user_id}")
            raise HTTPException(
                status_code=404, 
                detail=f"Credentials not found for user {user_id}"
            )
        
        logger.info(f"✅ Credentials retrieved for user {user_id}")
        
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
        
        # Проверка валидности данных
        if len(login) < 3 or len(login) > 100:
            await update.message.reply_text("❌ Логин должен быть от 3 до 100 символов.")
            return
        
        if len(password) < 6 or len(password) > 100:
            await update.message.reply_text("❌ Пароль должен быть от 6 до 100 символов.")
            return
        
        # 1. Шифрование
        try:
            login_enc = encrypt_data(login)
            password_enc = encrypt_data(password)
            
            if not login_enc or not password_enc:
                await update.message.reply_text("❌ Ошибка шифрования. Обратитесь к администратору.")
                return
        except Exception as e:
            logger.error(f"Encryption error for user {user_id}: {e}")
            await update.message.reply_text("❌ Ошибка при шифровании данных.")
            return

        # 2. Сохранение в локальной БД (только зашифрованные данные)
        try:
            await save_encrypted_credentials(user_id, login_enc, password_enc)
            await update.message.reply_text("✅ Ваши данные Pocket Option зашифрованы и сохранены локально.")
            logger.info(f"✅ User {user_id} credentials saved successfully")
        except Exception as e:
            logger.error(f"Database error for user {user_id}: {e}")
            await update.message.reply_text("❌ Ошибка при сохранении данных. Попробуйте позже.")
    else:
        await update.message.reply_text(
            "📝 Использование: /set_po [логин] [пароль]\n\n"
            "⚠️ *Внимание*: Не используйте реальные данные для тестирования!\n"
            "Пример: /set_po test_login test_password"
        )


async def request_signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /signal (запрос к Ядру Render через Supabase)."""
    user_id = update.effective_user.id
    
    # Проверка, есть ли сохраненные учетные данные
    try:
        credentials = await get_encrypted_data_from_local_db(user_id)
        if not credentials:
            await update.message.reply_text(
                "❌ Учетные данные Pocket Option не найдены.\n"
                "Используйте команду /set_po для их сохранения."
            )
            return
    except Exception as e:
        logger.error(f"❌ Error checking credentials for user {user_id}: {e}")
        await update.message.reply_text("❌ Ошибка при проверке учетных данных.")
        return
    
    try:
        # Запись запроса в таблицу signal_requests (Supabase)
        response = supabase.table("signal_requests").insert({
            'user_id': user_id,
            'request_type': 'latest_signal',
            'status': 'pending'
        }).execute()
        
        logger.info(f"✅ Signal request created for user {user_id}")
        
        await update.message.reply_text(
            "⏳ Запрос на сигнал отправлен!\n\n"
            "Ядро Анализа (Render) обработает его в ближайшее время.\n"
            "Вы получите уведомление, когда сигнал будет готов."
        )
        
    except Exception as e:
        logger.error(f"❌ Supabase error for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ Ошибка при отправке запроса в базу данных.\n"
            "Попробуйте позже или обратитесь к администратору."
        )


def run_telegram_bot():
    """Запускает Telegram-бот."""
    if not TELEGRAM_BOT_TOKEN_UI:
        logger.error("🚫 TELEGRAM_BOT_TOKEN_UI не задан. Бот не будет запущен.")
        return

    try:
        logger.info("🤖 Инициализация Telegram-бота...")
        application = Application.builder().token(TELEGRAM_BOT_TOKEN_UI).build()

        # Регистрация обработчиков команд
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("set_po", set_po_command))
        application.add_handler(CommandHandler("signal", request_signal_command))
        
        logger.info("✅ Обработчики команд зарегистрированы")
        logger.info("🚀 Запуск Telegram-бота в режиме polling...")
        
        # Запуск бота (без блокировки)
        application.run_polling(
            poll_interval=1.0, 
            timeout=10, 
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске Telegram-бота: {e}")
        raise


# --- 3. Объединение и Запуск ---

async def main():
    """Главная асинхронная функция, запускающая оба процесса."""
    logger.info("="*60)
    logger.info("🚀 Запуск UI-Бота (Telegram + API Server)...")
    logger.info("="*60)
    
    # Вывод информации о конфигурации
    logger.info(f"📡 API Server: http://0.0.0.0:{os.getenv('PORT', 8000)}")
    logger.info(f"🤖 Telegram Bot: {'Configured' if TELEGRAM_BOT_TOKEN_UI else 'Not configured'}")
    logger.info(f"🗄️ Supabase: {'Connected' if SUPABASE_URL and SUPABASE_KEY else 'Not configured'}")
    logger.info(f"🔐 Encryption: {'Enabled' if os.getenv('ENCRYPTION_KEY') else 'Disabled'}")
    logger.info("="*60)

    try:
        # 1. Запуск Telegram Bot в отдельном потоке
        logger.info("🔄 Запуск Telegram-бота...")
        telegram_task = asyncio.to_thread(run_telegram_bot)
        
        # 2. Настройка и запуск FastAPI (uvicorn)
        # При деплое на Bothost, порт может быть задан хостингом (обычно PORT=8000)
        port = int(os.getenv("PORT", 8000))
        logger.info(f"🔄 Запуск API-сервера на порту {port}...")
        
        config = uvicorn.Config(
            api_app, 
            host="0.0.0.0", 
            port=port, 
            log_level="info",
            access_log=True
        )
        server = uvicorn.Server(config)
        
        api_task = asyncio.create_task(server.serve())
        
        logger.info("✅ Все сервисы запущены успешно!")
        logger.info("="*60)

        # Ждем, пока оба процесса работают
        await asyncio.gather(telegram_task, api_task)
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n" + "="*60)
        logger.info("👋 Получен сигнал остановки (Ctrl+C)")
        logger.info("🛑 Оба процесса остановлены")
        logger.info("="*60)
    except Exception as e:
        logger.error(f"\n❌ Неожиданная ошибка: {e}")
        raise
