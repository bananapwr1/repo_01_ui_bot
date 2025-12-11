import os
import logging
import asyncio
import sqlite3
import requests
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from dotenv import load_dotenv
from cryptography.fernet import Fernet # Для шифрования
from typing import Optional, Dict, Any

# ============================ КОНФИГУРАЦИЯ ============================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") # 8218904195:AAGinuQn0eGe8qYm-P5EOPwVq3awPyJ5fD8
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY") # Ключ для Fernet (из Env Vars)
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")

if not all([BOT_TOKEN, ENCRYPTION_KEY, SUPABASE_URL, SUPABASE_KEY]):
    raise ValueError("❌ Отсутствуют ключевые переменные окружения.")

DB_PATH = os.getenv("SQLITE_DB_NAME", "user_data.db") # user_data.db
SUPPORT_CONTACT = "@banana_pwr"

# Состояния FSM
(WAITING_FOR_EMAIL, WAITING_FOR_PASSWORD) = range(2)

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========================== КЛАССЫ И УТИЛИТЫ ==========================

class SQLiteManager:
    """Управление локальной базой данных пользователей."""
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.init_db()

    def init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                subscription_type TEXT DEFAULT 'none',
                po_email TEXT,
                po_password_enc TEXT, -- Encrypted password
                fsm_state TEXT,
                created_at TEXT
            )
        ''')
        self.conn.commit()

    def get_user(self, telegram_id) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        row = cursor.fetchone()
        if row:
            columns = [col[0] for col in cursor.description]
            return dict(zip(columns, row))
        return None

    def create_or_get_user(self, telegram_id, username):
        user = self.get_user(telegram_id)
        if user:
            return user
        
        created_at = datetime.now().isoformat()
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO users (telegram_id, username, created_at) 
            VALUES (?, ?, ?)
        ''', (telegram_id, username, created_at))
        self.conn.commit()
        return self.get_user(telegram_id)

    def update_user(self, telegram_id, data: Dict[str, Any]):
        set_clause = ', '.join([f'{key} = ?' for key in data.keys()])
        values = list(data.values())
        values.append(telegram_id)
        
        cursor = self.conn.cursor()
        cursor.execute(f'UPDATE users SET {set_clause} WHERE telegram_id = ?', values)
        self.conn.commit()
    
    def get_po_credentials(self, telegram_id):
        user = self.get_user(telegram_id)
        if user and user['po_email'] and user['po_password_enc']:
            f = Fernet(ENCRYPTION_KEY.encode())
            try:
                # Дешифрование данных
                password_dec = f.decrypt(user['po_password_enc'].encode()).decode()
                return user['po_email'], password_dec
            except Exception as e:
                logger.error(f"Decryption error for user {telegram_id}: {e}")
                return user['po_email'], None
        return None, None

class SupabaseLiteManager:
    """Управление Supabase только для записи команд."""
    def __init__(self, url, key):
        self.url = url
        self.key = key
        self.headers = {
            'apikey': self.key,
            'Authorization': f'Bearer {self.key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal' # Запрашиваем минимальный ответ
        }

    async def save_signal_request(self, user_id, signal_type):
        """Записывает запрос сигнала в Supabase для обработки Ядром PA."""
        command_data = {
            'user_id': user_id,
            'request_type': signal_type,
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        }
        url = f"{self.url}/rest/v1/signal_requests" # Имя таблицы для запросов
        
        try:
            # Используем requests.post для простой записи
            response = requests.post(url, headers=self.headers, json=command_data)
            
            if response.status_code in [201, 204]:
                return True
            else:
                logger.error(f"Supabase POST error (signal_requests): Status {response.status_code}, Body: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Supabase network error: {e}")
            return False

# Инициализация
db_lite = SQLiteManager(DB_PATH)
supabase_lite = SupabaseLiteManager(SUPABASE_URL, SUPABASE_KEY)

# =========================== ХЭНДЛЕРЫ КОМАНД ===========================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🏠 Главное меню"""
    user_id = update.effective_user.id
    username = update.effective_user.username or 'N/A'
    
    user_data = db_lite.create_or_get_user(user_id, username)
    subscription = user_data.get('subscription_type', 'none').upper()
    
    keyboard = [
        [InlineKeyboardButton("⚡ SHORT сигнал", callback_data='req_short'), 
         InlineKeyboardButton("🔵 LONG сигнал", callback_data='req_long')],
        [InlineKeyboardButton("💳 Настройка PO", callback_data='settings_po'),
         InlineKeyboardButton("💎 Тарифы", callback_data='plans')],
        [InlineKeyboardButton("❓ Помощь / Поддержка", callback_data='help')]
    ]
    
    await update.message.reply_text(
        f"🏠 *Главное меню*\n\n"
        f"🤖 Ваш ID: `{user_id}`\n"
        f"📋 *Текущий тариф:* {subscription}\n"
        f"Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    if data == 'req_short' or data == 'req_long':
        signal_type = data.split('_')[1]
        
        # Проверка лимитов (здесь должна быть сложная логика, но для Bot #1 мы ее упрощаем)
        user_data = db_lite.get_user(user_id)
        if user_data.get('subscription_type') == 'none' and (datetime.now() - datetime.fromisoformat(user_data.get('created_at')) > timedelta(days=1)):
             # Пример: если FREE и прошло 24 часа
             await query.edit_message_text("❌ Ваш бесплатный лимит исчерпан. Пожалуйста, приобретите подписку.",
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Тарифы", callback_data='plans')]]))
             return

        # 1. Отправляем запрос в Supabase для обработки Ядром PA
        success = await supabase_lite.save_signal_request(user_id, signal_type)
        
        if success:
            await query.edit_message_text(
                f"✅ *{signal_type.upper()} сигнал запрошен*\n\n"
                "Сигнал отправлен в торговое ядро...\n"
                "Ожидайте уведомления!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data='start')]]),
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ *Ошибка отправки команды SIGNAL*.\n\nПопробуйте позже или проверьте соединение с Supabase.",
                                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data='start')]]),
                                           parse_mode='Markdown')
        
    elif data == 'settings_po':
        # Запуск FSM для ввода данных PO
        await query.edit_message_text(
            "💳 *Настройка Pocket Option*\n\n"
            "Введите ваш **Email** для Pocket Option:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data='cancel_fsm')]]),
            parse_mode='Markdown'
        )
        return WAITING_FOR_EMAIL # Переход в состояние FSM
        
    elif data == 'cancel_fsm' or data == 'start':
        # Сброс FSM и возврат в меню
        await start_command(update, context)
        return ConversationHandler.END
        
    # Добавьте хэндлеры для 'plans' и 'help' с их собственными сообщениями
    elif data == 'plans':
        await query.edit_message_text("💎 *Тарифы*\n\n(Подробная информация о тарифах...)")
        await start_command(update, context)

    elif data == 'help':
        await query.edit_message_text(f"❓ *Помощь*\n\nОбратитесь к {SUPPORT_CONTACT}")
        await start_command(update, context)

    await query.edit_message_reply_markup(reply_markup=create_main_menu_keyboard(user_id))

def create_main_menu_keyboard(user_id):
    # Вспомогательная функция для генерации клавиатуры (как в start_command)
    keyboard = [
        [InlineKeyboardButton("⚡ SHORT сигнал", callback_data='req_short'), 
         InlineKeyboardButton("🔵 LONG сигнал", callback_data='req_long')],
        [InlineKeyboardButton("💳 Настройка PO", callback_data='settings_po'),
         InlineKeyboardButton("💎 Тарифы", callback_data='plans')],
        [InlineKeyboardButton("❓ Помощь / Поддержка", callback_data='help')]
    ]
    return InlineKeyboardMarkup(keyboard)

# =========================== FSM (Pocket Option Login) ===========================

async def fsm_enter_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Первый шаг FSM: ввод email."""
    email = update.message.text
    context.user_data['po_email'] = email
    
    await update.message.reply_text("Отлично. Теперь введите ваш **Пароль** для Pocket Option:")
    return WAITING_FOR_PASSWORD # Переход в следующее состояние

async def fsm_enter_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Второй шаг FSM: ввод пароля, шифрование и сохранение."""
    password = update.message.text
    user_id = update.effective_user.id

    # 1. Шифрование пароля
    f = Fernet(ENCRYPTION_KEY.encode())
    encrypted_password_bytes = f.encrypt(password.encode())
    encrypted_password_str = encrypted_password_bytes.decode()

    # 2. Сохранение в SQLite
    db_lite.update_user(user_id, {
        'po_email': context.user_data['po_email'],
        'po_password_enc': encrypted_password_str
    })
    
    # 3. Уведомление
    await update.message.reply_text(
        "✅ *Данные Pocket Option сохранены и зашифрованы!*\n\n"
        "Теперь вы можете использовать автоторговлю (если у вас VIP тариф).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data='start')]]),
        parse_mode='Markdown'
    )
    # Завершение FSM
    return ConversationHandler.END

async def fsm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена FSM."""
    await update.message.reply_text("Операция отменена. Возврат в главное меню.",
                                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data='start')]]))
    return ConversationHandler.END

# =========================== ЗАПУСК БОТА ===========================

async def set_default_commands(application: Application):
    """Установка команд бота."""
    commands = [BotCommand(command, description) for command, description in [
        ("start", "🏠 Главное меню"),
        ("plans", "💎 Тарифы"),
        ("short", "⚡ SHORT сигнал"),
        ("long", "🔵 LONG сигнал"),
    ]]
    await application.bot.set_my_commands(commands)

def main():
    application = Application.builder().token(BOT_TOKEN).post_init(set_default_commands).build()
    
    # Хэндлеры для команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("plans", start_command)) # Перенаправляем на start для единого меню
    
    # Хэндлер для FSM (Настройка PO)
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_callback_query, pattern='^settings_po$')],
        states={
            WAITING_FOR_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, fsm_enter_email)],
            WAITING_FOR_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, fsm_enter_password)],
        },
        fallbacks=[CommandHandler('cancel', fsm_cancel), CallbackQueryHandler(fsm_cancel, pattern='^cancel_fsm$')]
    )
    application.add_handler(conv_handler)
    
    # Хэндлер для CallbackQuery (основные кнопки)
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    logger.info("🚀 Client UI Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
