# Исправленный импорт для supabase >= 2.0
try:
    from supabase import create_client, Client
    SUPABASE_NEW = True
except ImportError:
    # Для старых версий
    from supabase import create_client
    SUPABASE_NEW = False
# Инициализация Supabase (совместимость с версиями)
try:
    if SUPABASE_NEW:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    else:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✅ Supabase подключен")
except Exception as e:
    logger.error(f"❌ Ошибка Supabase: {e}")
    supabase = None  # Бот будет работать без Supabase
#!/usr/bin/env python3
"""
BOTHOST БОТ #1: ИНТЕРФЕЙСНЫЙ БОТ
Оптимизированная версия для деплоя
"""

import os
import sqlite3
import logging
import asyncio
from datetime import datetime
from typing import Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from supabase import create_client
# ...
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import pytz

# ============ НАСТРОЙКА ЛОГИРОВАНИЯ ============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot_ui.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ============ ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ============
load_dotenv()

# Проверка обязательных переменных
REQUIRED_ENV_VARS = ['BOT_TOKEN', 'NEXT_PUBLIC_SUPABASE_URL', 
                     'NEXT_PUBLIC_SUPABASE_ANON_KEY', 'ENCRYPTION_KEY']

missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    logger.error(f"❌ Отсутствуют переменные: {missing_vars}")
    raise ValueError(f"Отсутствуют переменные окружения: {missing_vars}")

# ============ КОНСТАНТЫ ============
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
SQLITE_DB_NAME = os.getenv("SQLITE_DB_NAME", "user_data.db")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "7746862973").split(",") if x.strip()]

# Инициализация
cipher_suite = Fernet(ENCRYPTION_KEY.encode())
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# ============ СОСТОЯНИЯ FSM ============
ASK_PO_LOGIN, ASK_PO_PASSWORD = range(2)

# ============ SQLITE БАЗА ДАННЫХ ============
def init_database():
    """Инициализация SQLite базы данных"""
    conn = sqlite3.connect(SQLITE_DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    
    # Пользователи
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            subscription_type TEXT DEFAULT 'free',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # PO логины (зашифрованные)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS po_credentials (
            user_id INTEGER PRIMARY KEY,
            po_login_encrypted TEXT NOT NULL,
            po_password_encrypted TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Состояния FSM
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_states (
            user_id INTEGER PRIMARY KEY,
            state TEXT,
            data TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    return conn

# Глобальное подключение к БД
DB_CONN = init_database()

# ============ ХЕЛПЕР-ФУНКЦИИ ============
def get_user(user_id: int) -> Optional[Dict]:
    """Получить пользователя из БД"""
    cursor = DB_CONN.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))
    return None

def save_user(user_id: int, username: str, first_name: str, last_name: str = ""):
    """Сохранить пользователя"""
    cursor = DB_CONN.cursor()
    if get_user(user_id):
        cursor.execute('''
            UPDATE users SET username=?, first_name=?, last_name=?
            WHERE user_id=?
        ''', (username, first_name, last_name, user_id))
    else:
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name))
    DB_CONN.commit()

def save_po_credentials(user_id: int, login: str, password: str):
    """Сохранить зашифрованные PO данные"""
    encrypted_login = cipher_suite.encrypt(login.encode()).decode()
    encrypted_password = cipher_suite.encrypt(password.encode()).decode()
    
    cursor = DB_CONN.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO po_credentials (user_id, po_login_encrypted, po_password_encrypted)
        VALUES (?, ?, ?)
    ''', (user_id, encrypted_login, encrypted_password))
    DB_CONN.commit()

def get_po_credentials(user_id: int) -> Optional[tuple]:
    """Получить PO данные"""
    cursor = DB_CONN.cursor()
    cursor.execute(
        'SELECT po_login_encrypted, po_password_encrypted FROM po_credentials WHERE user_id = ?',
        (user_id,)
    )
    result = cursor.fetchone()
    if result:
        login = cipher_suite.decrypt(result[0].encode()).decode()
        password = cipher_suite.decrypt(result[1].encode()).decode()
        return login, password
    return None

# ============ КОМАНДЫ БОТА ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start"""
    user = update.effective_user
    save_user(user.id, user.username or "", user.first_name, user.last_name or "")
    
    po_creds = get_po_credentials(user.id)
    
    if po_creds:
        keyboard = [
            [InlineKeyboardButton("📈 Короткий сигнал", callback_data="short_signal")],
            [InlineKeyboardButton("💼 Мои подписки", callback_data="plans")],
            [InlineKeyboardButton("⚙️ Изменить PO-логин", callback_data="change_po")]
        ]
        text = f"👋 Привет, {user.first_name}!\n✅ Ваш PO-аккаунт привязан."
    else:
        keyboard = [
            [InlineKeyboardButton("🔗 Привязать PO-аккаунт", callback_data="setup_po")]
        ]
        text = f"👋 Добро пожаловать, {user.first_name}!\nПривяжите PO-аккаунт для начала."
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /plans"""
    text = """
📊 **Тарифные планы:**

• 🆓 **Free** (бесплатно)
  └ 3 сигнала в день

• 🥈 **Pro** ($19/месяц)
  └ 10 сигналов в день
  └ Приоритетная очередь

• 🥇 **Premium** ($49/месяц)
  └ Неограниченные сигналы
  └ Максимальный приоритет
  └ AI-анализ портфеля
    """
    
    keyboard = [
        [InlineKeyboardButton("🆓 Free", callback_data="plan_free")],
        [InlineKeyboardButton("🥈 Pro", callback_data="plan_pro")],
        [InlineKeyboardButton("🥇 Premium", callback_data="plan_premium")]
    ]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /status"""
    user = update.effective_user
    user_data = get_user(user.id)
    po_creds = get_po_credentials(user.id)
    
    if user_data:
        po_status = "✅ Привязан" if po_creds else "❌ Не привязан"
        text = f"""
📊 **Ваш статус:**
• ID: {user.id}
• Имя: {user.first_name}
• Подписка: {user_data.get('subscription_type', 'free')}
• PO-аккаунт: {po_status}
        """
    else:
        text = "Вы еще не зарегистрированы. Используйте /start"
    
    await update.message.reply_text(text, parse_mode='Markdown')

# ============ ОБРАБОТКА КНОПОК ============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline-кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "short_signal":
        await handle_short_signal(user_id, query)
    elif data == "plans":
        await show_plans(query)
    elif data == "setup_po":
        await start_po_setup(query)
    elif data.startswith("plan_"):
        await handle_plan_selection(data, query)

async def handle_short_signal(user_id: int, query):
    """Запрос короткого сигнала"""
    po_creds = get_po_credentials(user_id)
    
    if not po_creds:
        await query.edit_message_text(
            "❌ Сначала привяжите PO-аккаунт!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Привязать PO", callback_data="setup_po")]
            ])
        )
        return
    
    try:
        # Сохраняем запрос в Supabase
        timestamp = datetime.now(MOSCOW_TZ).isoformat()
        supabase.table("signal_requests").insert({
            "user_id": user_id,
            "po_login": po_creds[0],
            "request_type": "short",
            "status": "pending",
            "created_at": timestamp
        }).execute()
        
        await query.edit_message_text(
            "✅ Запрос на короткий сигнал отправлен!\n"
            "Ядро анализирует рынок и скоро пришлет сигнал."
        )
        
    except Exception as e:
        logger.error(f"Ошибка Supabase: {e}")
        await query.edit_message_text("❌ Ошибка при отправке запроса.")

async def show_plans(query):
    """Показать планы"""
    await plans(None, type('Context', (), {'args': []})())

async def start_po_setup(query):
    """Начать привязку PO"""
    from telegram.ext import ConversationHandler
    await query.edit_message_text("Введите ваш PO-логин:")
    return ASK_PO_LOGIN

async def handle_plan_selection(plan: str, query):
    """Обработка выбора тарифа"""
    plan_map = {"plan_free": "free", "plan_pro": "pro", "plan_premium": "premium"}
    selected = plan_map.get(plan, "free")
    
    cursor = DB_CONN.cursor()
    cursor.execute(
        'UPDATE users SET subscription_type = ? WHERE user_id = ?',
        (selected, query.from_user.id)
    )
    DB_CONN.commit()
    
    await query.edit_message_text(f"✅ Тариф '{selected}' выбран!")

# ============ FSM ДЛЯ PO-ЛОГИНА ============
async def ask_po_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение PO логина"""
    context.user_data['po_login'] = update.message.text
    await update.message.reply_text("Теперь введите ваш PO-пароль:")
    return ASK_PO_PASSWORD

async def ask_po_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение PO пароля"""
    po_login = context.user_data.get('po_login')
    po_password = update.message.text
    
    if po_login:
        save_po_credentials(update.effective_user.id, po_login, po_password)
        await update.message.reply_text("✅ PO-аккаунт успешно привязан!")
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена FSM"""
    context.user_data.clear()
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

# ============ ЗАПУСК БОТА ============
def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation Handler для PO логина
    po_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_po_setup, pattern='^setup_po$')],
        states={
            ASK_PO_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_po_login)],
            ASK_PO_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_po_password)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("plans", plans))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(po_conv_handler)
    
    # Запускаем бота
    logger.info("🤖 Бот #1 запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()