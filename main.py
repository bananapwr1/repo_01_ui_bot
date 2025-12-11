#!/usr/bin/env python3
"""
BOTHOST БОТ #1: ИНТЕРФЕЙСНЫЙ БОТ
Только пользовательский интерфейс, SQLite для пользователей
Supabase ТОЛЬКО для записи signal_requests
"""

import os
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from supabase import create_client, Client
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import pytz

# Загружаем переменные окружения
load_dotenv()

# ============== НАСТРОЙКИ ==============
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
SQLITE_DB_NAME = os.getenv("SQLITE_DB_NAME", "user_data.db")

# Проверка обязательных переменных
if not all([BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, ENCRYPTION_KEY]):
    raise ValueError("Missing required environment variables!")

# Инициализация шифрования
cipher_suite = Fernet(ENCRYPTION_KEY.encode())

# Инициализация Supabase (ТОЛЬКО для signal_requests)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============== СОСТОЯНИЯ FSM ==============
class States(Enum):
    ASK_PO_LOGIN = 1
    ASK_PO_PASSWORD = 2

# ============== SQLite ФУНКЦИИ ==============
def init_sqlite() -> sqlite3.Connection:
    """Инициализация SQLite базы данных"""
    conn = sqlite3.connect(SQLITE_DB_NAME)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            subscription_type TEXT DEFAULT 'free',
            subscription_end DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица PO-логинов (зашифрованные)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS po_credentials (
            user_id INTEGER PRIMARY KEY,
            po_login_encrypted TEXT NOT NULL,
            po_password_encrypted TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Таблица состояний FSM
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

# Глобальное подключение к SQLite
DB_CONN = init_sqlite()

def get_user(user_id: int) -> Optional[Dict]:
    """Получить пользователя из SQLite"""
    cursor = DB_CONN.cursor()
    cursor.execute(
        'SELECT * FROM users WHERE user_id = ?',
        (user_id,)
    )
    row = cursor.fetchone()
    
    if row:
        columns = [description[0] for description in cursor.description]
        return dict(zip(columns, row))
    return None

def save_user(user_id: int, username: str, first_name: str, last_name: str = ""):
    """Сохранить/обновить пользователя в SQLite"""
    cursor = DB_CONN.cursor()
    
    user = get_user(user_id)
    if user:
        cursor.execute('''
            UPDATE users 
            SET username = ?, first_name = ?, last_name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
        ''', (username, first_name, last_name, user_id))
    else:
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name))
    
    DB_CONN.commit()

def get_state(user_id: int) -> Optional[Tuple[str, str]]:
    """Получить состояние FSM из SQLite"""
    cursor = DB_CONN.cursor()
    cursor.execute(
        'SELECT state, data FROM user_states WHERE user_id = ?',
        (user_id,)
    )
    result = cursor.fetchone()
    return result if result else (None, None)

def set_state(user_id: int, state: Optional[str], data: Optional[str] = None):
    """Установить состояние FSM в SQLite"""
    cursor = DB_CONN.cursor()
    
    if state is None:
        cursor.execute(
            'DELETE FROM user_states WHERE user_id = ?',
            (user_id,)
        )
    else:
        cursor.execute('''
            INSERT OR REPLACE INTO user_states (user_id, state, data, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, state, data))
    
    DB_CONN.commit()

def save_po_credentials(user_id: int, login: str, password: str):
    """Сохранить зашифрованные PO-логин и пароль в SQLite"""
    encrypted_login = cipher_suite.encrypt(login.encode()).decode()
    encrypted_password = cipher_suite.encrypt(password.encode()).decode()
    
    cursor = DB_CONN.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO po_credentials (user_id, po_login_encrypted, po_password_encrypted)
        VALUES (?, ?, ?)
    ''', (user_id, encrypted_login, encrypted_password))
    
    DB_CONN.commit()

def get_po_credentials(user_id: int) -> Optional[Tuple[str, str]]:
    """Получить расшифрованные PO-логин и пароль из SQLite"""
    cursor = DB_CONN.cursor()
    cursor.execute(
        'SELECT po_login_encrypted, po_password_encrypted FROM po_credentials WHERE user_id = ?',
        (user_id,)
    )
    result = cursor.fetchone()
    
    if result:
        encrypted_login, encrypted_password = result
        login = cipher_suite.decrypt(encrypted_login.encode()).decode()
        password = cipher_suite.decrypt(encrypted_password.encode()).decode()
        return login, password
    return None

# ============== ОСНОВНЫЕ КОМАНДЫ ==============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id
    
    # Сохраняем пользователя в SQLite
    save_user(
        user_id=user_id,
        username=user.username or "",
        first_name=user.first_name,
        last_name=user.last_name or ""
    )
    
    # Проверяем, есть ли PO-логин
    po_creds = get_po_credentials(user_id)
    
    if po_creds:
        # У пользователя уже есть PO-логин
        keyboard = [
            [InlineKeyboardButton("📈 Короткий сигнал", callback_data="short_signal")],
            [InlineKeyboardButton("💼 Мои подписки", callback_data="plans")],
            [InlineKeyboardButton("⚙️ Изменить PO-логин", callback_data="change_po")]
        ]
        text = (
            f"👋 Привет, {user.first_name}!\n\n"
            "✅ Ваш PO-аккаунт привязан.\n"
            "Вы можете запрашивать торговые сигналы."
        )
    else:
        # Нужно привязать PO-логин
        keyboard = [
            [InlineKeyboardButton("🔗 Привязать PO-аккаунт", callback_data="setup_po")]
        ]
        text = (
            f"👋 Добро пожаловать, {user.first_name}!\n\n"
            "Для начала работы необходимо привязать ваш PO-аккаунт.\n"
            "Это нужно для персонализации сигналов."
        )
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        text=text,
        reply_markup=reply_markup
    )

async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /plans"""
    user_id = update.effective_user.id
    
    # Получаем данные о подписке из SQLite
    user = get_user(user_id)
    
    if user and user.get('subscription_type'):
        subscription = user['subscription_type']
        end_date = user.get('subscription_end', 'не указана')
        
        text = (
            f"📊 **Ваша подписка:**\n\n"
            f"• Тип: {subscription}\n"
            f"• Действует до: {end_date}\n\n"
            f"Доступные тарифы:\n"
            f"• 🆓 Free: 3 сигнала в день\n"
            f"• 🥈 Pro: 10 сигналов в день\n"
            f"• 🥇 Premium: неограниченно"
        )
    else:
        text = (
            "📊 **Тарифные планы:**\n\n"
            "• 🆓 **Free** (бесплатно)\n"
            "  └ 3 сигнала в день\n\n"
            "• 🥈 **Pro** ($19/месяц)\n"
            "  └ 10 сигналов в день\n"
            "  └ Приоритетная очередь\n\n"
            "• 🥇 **Premium** ($49/месяц)\n"
            "  └ Неограниченные сигналы\n"
            "  └ Максимальный приоритет\n"
            "  └ AI-анализ вашего портфеля"
        )
    
    keyboard = [
        [InlineKeyboardButton("🆓 Выбрать Free", callback_data="plan_free")],
        [InlineKeyboardButton("🥈 Выбрать Pro", callback_data="plan_pro")],
        [InlineKeyboardButton("🥇 Выбрать Premium", callback_data="plan_premium")]
    ]
    
    await update.message.reply_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /status"""
    user_id = update.effective_user.id
    
    # Получаем данные из SQLite
    user = get_user(user_id)
    po_creds = get_po_credentials(user_id)
    
    if user:
        subscription = user.get('subscription_type', 'free')
        end_date = user.get('subscription_end', 'не указана')
        po_status = "✅ Привязан" if po_creds else "❌ Не привязан"
        
        text = (
            f"📊 **Ваш статус:**\n\n"
            f"• ID: {user_id}\n"
            f"• Имя: {user.get('first_name', '')}\n"
            f"• Подписка: {subscription}\n"
            f"• Действует до: {end_date}\n"
            f"• PO-аккаунт: {po_status}\n\n"
            f"Используйте /plans для изменения подписки."
        )
    else:
        text = "Вы еще не зарегистрированы. Используйте /start"
    
    await update.message.reply_text(
        text=text,
        parse_mode='Markdown'
    )

# ============== ОБРАБОТЧИКИ CALLBACK ==============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline-кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data == "short_signal":
        await handle_short_signal(user_id, query)
    
    elif data == "plans":
        await plans_from_button(query)
    
    elif data == "setup_po":
        await setup_po_start(query)
    
    elif data == "change_po":
        await change_po_start(query)
    
    elif data.startswith("plan_"):
        await handle_plan_selection(data, query)
    
    else:
        await query.edit_message_text("Неизвестная команда")

async def handle_short_signal(user_id: int, query):
    """✅ ЕДИНСТВЕННАЯ функция записи в Supabase"""
    try:
        # Проверяем PO-логин в SQLite
        po_creds = get_po_credentials(user_id)
        
        if not po_creds:
            await query.edit_message_text(
                text="❌ Сначала привяжите PO-аккаунт!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Привязать PO", callback_data="setup_po")]
                ])
            )
            return
        
        # ✅ ЗАПИСЫВАЕМ ЗАПРОС В SUPABASE
        moscow_tz = pytz.timezone('Europe/Moscow')
        timestamp = datetime.now(moscow_tz).isoformat()
        
        supabase.table("signal_requests").insert({
            "user_id": user_id,
            "po_login": po_creds[0],  # Логин из SQLite (расшифрованный)
            "request_type": "short",
            "status": "pending",
            "created_at": timestamp
        }).execute()
        
        logger.info(f"Signal request saved to Supabase for user {user_id}")
        
        await query.edit_message_text(
            text="✅ Запрос на короткий сигнал отправлен в торговое ядро!\n\n"
                 "Ядро анализирует рынок и скоро пришлет сигнал.\n"
                 "Обычно это занимает 1-2 минуты."
        )
        
    except Exception as e:
        logger.error(f"Error saving to Supabase: {e}")
        await query.edit_message_text(
            text="❌ Ошибка при отправке запроса. Попробуйте позже."
        )

async def plans_from_button(query):
    """Показать планы из inline-кнопки"""
    await query.edit_message_text(
        text=(
            "📊 **Тарифные планы:**\n\n"
            "• 🆓 **Free** (бесплатно)\n"
            "  └ 3 сигнала в день\n\n"
            "• 🥈 **Pro** ($19/месяц)\n"
            "  └ 10 сигнала в день\n"
            "  └ Приоритетная очередь\n\n"
            "• 🥇 **Premium** ($49/месяц)\n"
            "  └ Неограниченные сигналы\n"
            "  └ Максимальный приоритет\n"
            "  └ AI-анализ вашего портфеля"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆓 Выбрать Free", callback_data="plan_free")],
            [InlineKeyboardButton("🥈 Выбрать Pro", callback_data="plan_pro")],
            [InlineKeyboardButton("🥇 Выбрать Premium", callback_data="plan_premium")]
        ]),
        parse_mode='Markdown'
    )

async def setup_po_start(query):
    """Начать процесс привязки PO-аккаунта"""
    set_state(query.from_user.id, "ASK_PO_LOGIN")
    
    await query.edit_message_text(
        text="🔗 **Привязка PO-аккаунта**\n\n"
             "Пожалуйста, введите ваш PO-логин:",
        parse_mode='Markdown'
    )

async def change_po_start(query):
    """Начать процесс изменения PO-аккаунта"""
    set_state(query.from_user.id, "ASK_PO_LOGIN")
    
    await query.edit_message_text(
        text="✏️ **Изменение PO-аккаунта**\n\n"
             "Пожалуйста, введите новый PO-логин:",
        parse_mode='Markdown'
    )

async def handle_plan_selection(plan: str, query):
    """Обработчик выбора тарифа"""
    plan_map = {
        "plan_free": "free",
        "plan_pro": "pro",
        "plan_premium": "premium"
    }
    
    selected = plan_map.get(plan, "free")
    
    # Сохраняем в SQLite
    cursor = DB_CONN.cursor()
    cursor.execute('''
        UPDATE users 
        SET subscription_type = ?, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
    ''', (selected, query.from_user.id))
    DB_CONN.commit()
    
    await query.edit_message_text(
        text=f"✅ Тариф '{selected}' успешно выбран!\n\n"
             f"Используйте /status для проверки вашего статуса."
    )

# ============== FSM ДЛЯ PO-ЛОГИНА ==============
async def handle_po_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода PO-логина"""
    user_id = update.effective_user.id
    po_login = update.message.text.strip()
    
    # Сохраняем login во временные данные
    set_state(user_id, "ASK_PO_PASSWORD", po_login)
    
    await update.message.reply_text(
        "Теперь введите ваш PO-пароль:"
    )
    
    return States.ASK_PO_PASSWORD

async def handle_po_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода PO-пароля"""
    user_id = update.effective_user.id
    po_password = update.message.text.strip()
    
    # Получаем login из временных данных
    state, data = get_state(user_id)
    po_login = data
    
    if not po_login:
        await update.message.reply_text("Ошибка: логин не найден. Начните заново.")
        set_state(user_id, None)
        return ConversationHandler.END
    
    # ✅ Сохраняем в SQLite (зашифровано)
    save_po_credentials(user_id, po_login, po_password)
    
    # Очищаем состояние
    set_state(user_id, None)
    
    await update.message.reply_text(
        "✅ PO-аккаунт успешно привязан!\n\n"
        "Теперь вы можете запрашивать торговые сигналы."
    )
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена FSM"""
    user_id = update.effective_user.id
    set_state(user_id, None)
    
    await update.message.reply_text(
        "Операция отменена."
    )
    
    return ConversationHandler.END

# ============== ОСНОВНАЯ ФУНКЦИЯ ==============
def main():
    """Запуск бота #1"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation Handler для PO-логина
    po_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(setup_po_start, pattern="^setup_po$"),
                     CallbackQueryHandler(change_po_start, pattern="^change_po$")],
        states={
            States.ASK_PO_LOGIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_po_login)
            ],
            States.ASK_PO_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_po_password)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("plans", plans))
    application.add_handler(CommandHandler("status", status))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Conversation Handler
    application.add_handler(po_conv_handler)
    
    # Запуск бота
    logger.info("Bot #1 (UI) starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
