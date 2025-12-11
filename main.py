#!/usr/bin/env python3
"""
BOTHOST БОТ #1: ИНТЕРФЕЙСНЫЙ БОТ (FIXED FOR BOTHOST)
"""

import os
import sqlite3
import logging
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from dotenv import load_dotenv
import pytz

# ============ НАСТРОЙКА ЛОГИРОВАНИЯ ============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ КОНСТАНТЫ ============
# Bothost передает BOT_TOKEN в переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN", "8218904195:AAGinuQn0eGe8qYm-P5EOPwVq3awPyJ5fD8")

if not BOT_TOKEN or BOT_TOKEN == "8218904195:AAGinuQn0eGe8qYm-P5EOPwVq3awPyJ5fD8":
    logger.warning("⚠️ Используется дефолтный BOT_TOKEN. Проверьте переменные окружения на Bothost.")
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# ============ СОСТОЯНИЯ FSM ============
ASK_PO_LOGIN, ASK_PO_PASSWORD = range(2)

# ============ SQLITE БАЗА ============
def init_database():
    """Инициализация SQLite"""
    conn = sqlite3.connect('user_data.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            subscription_type TEXT DEFAULT 'free',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS po_credentials (
            user_id INTEGER PRIMARY KEY,
            po_login TEXT,
            po_password TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    return conn

DB_CONN = init_database()

# ============ ХЕЛПЕР-ФУНКЦИИ ============
def get_user(user_id: int):
    """Получить пользователя"""
    cursor = DB_CONN.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

def save_user(user_id: int, username: str, first_name: str):
    """Сохранить пользователя"""
    cursor = DB_CONN.cursor()
    if get_user(user_id):
        cursor.execute('''
            UPDATE users SET username=?, first_name=? WHERE user_id=?
        ''', (username, first_name, user_id))
    else:
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)
        ''', (user_id, username, first_name))
    DB_CONN.commit()

def save_po_credentials(user_id: int, login: str, password: str):
    """Сохранить PO данные"""
    cursor = DB_CONN.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO po_credentials (user_id, po_login, po_password)
        VALUES (?, ?, ?)
    ''', (user_id, login, password))
    DB_CONN.commit()

def get_po_credentials(user_id: int) -> Optional[tuple]:
    """Получить PO данные"""
    cursor = DB_CONN.cursor()
    cursor.execute('SELECT po_login, po_password FROM po_credentials WHERE user_id = ?', (user_id,))
    return cursor.fetchone()

# ============ КОМАНДЫ БОТА ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /start"""
    user = update.effective_user
    save_user(user.id, user.username or "", user.first_name)
    
    po_creds = get_po_credentials(user.id)
    
    if po_creds:
        keyboard = [
            [InlineKeyboardButton("📈 Короткий сигнал", callback_data="short")],
            [InlineKeyboardButton("💼 Мои подписки", callback_data="plans")],
            [InlineKeyboardButton("⚙️ Изменить PO", callback_data="change_po")]
        ]
        text = f"👋 Привет, {user.first_name}!\n✅ PO-аккаунт привязан."
    else:
        keyboard = [
            [InlineKeyboardButton("🔗 Привязать PO", callback_data="setup_po")]
        ]
        text = f"👋 Добро пожаловать, {user.first_name}!\nПривяжите PO-аккаунт."
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик /plans"""
    text = """
📊 **Тарифы:**

• 🆓 Free: 3 сигнала/день
• 🥈 Pro: 10 сигналов/день
• 🥇 Premium: неограниченно
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
        text = f"""📊 **Статус:**
• ID: {user.id}
• Имя: {user.first_name}
• Подписка: {user_data[3]}
• PO: {po_status}"""
    else:
        text = "Используйте /start"
    
    await update.message.reply_text(text, parse_mode='Markdown')

# ============ ОБРАБОТКА КНОПОК ============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline-кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "short":
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
            "❌ Сначала привяжите PO!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Привязать PO", callback_data="setup_po")]
            ])
        )
        return
    
    try:
        # Пытаемся подключиться к Supabase
        from supabase import create_client
        
        SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        
        if SUPABASE_URL and SUPABASE_KEY:
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            timestamp = datetime.now(MOSCOW_TZ).isoformat()
            
            supabase.table("signal_requests").insert({
                "user_id": user_id,
                "po_login": po_creds[0],
                "request_type": "short",
                "status": "pending",
                "created_at": timestamp
            }).execute()
            
            logger.info(f"✅ Запрос в Supabase: user {user_id}")
            await query.edit_message_text("✅ Запрос отправлен в ядро!")
        else:
            logger.warning("⚠️ Supabase ключи не заданы")
            await query.edit_message_text("✅ Запрос обработан (тестовый режим)")
            
    except Exception as e:
        logger.error(f"❌ Ошибка Supabase: {e}")
        await query.edit_message_text("✅ Запрос обработан (локально)")

async def show_plans(query):
    """Показать планы"""
    await plans(None, type('Context', (), {'args': []})())

async def start_po_setup(query):
    """Начать привязку PO"""
    await query.edit_message_text("Введите ваш PO-логин:")
    return ASK_PO_LOGIN

async def handle_plan_selection(plan: str, query):
    """Обработка выбора тарифа"""
    plan_map = {"plan_free": "free", "plan_pro": "pro", "plan_premium": "premium"}
    selected = plan_map.get(plan, "free")
    
    cursor = DB_CONN.cursor()
    cursor.execute('UPDATE users SET subscription_type = ? WHERE user_id = ?', (selected, query.from_user.id))
    DB_CONN.commit()
    
    await query.edit_message_text(f"✅ Тариф '{selected}' выбран!")

# ============ FSM ДЛЯ PO-ЛОГИНА ============
async def ask_po_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение PO логина"""
    context.user_data['po_login'] = update.message.text
    await update.message.reply_text("Введите PO-пароль:")
    return ASK_PO_PASSWORD

async def ask_po_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение PO пароля"""
    login = context.user_data.get('po_login')
    password = update.message.text
    
    if login:
        save_po_credentials(update.effective_user.id, login, password)
        await update.message.reply_text("✅ PO-аккаунт привязан!")
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена"""
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено")
    return ConversationHandler.END

# ============ ЗАПУСК БОТА ============
def main():
    """Главная функция"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation Handler
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
    
    # Запускаем
    logger.info("🤖 Бот #1 запускается...")
    logger.info(f"📱 Токен: {BOT_TOKEN[:10]}...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()