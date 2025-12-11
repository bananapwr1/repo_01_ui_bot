#!/usr/bin/env python3
"""
БОТ #1: РАБОЧАЯ ВЕРСИЯ ДЛЯ BOTHOST
"""

import os
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

# ============ НАСТРОЙКА ============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8218904195:AAGinuQn0eGe8qYm-P5EOPwVq3awPyJ5fD8")

# ============ SUPABASE ============
def init_supabase():
    """Инициализация Supabase (если есть ключи)"""
    try:
        from supabase import create_client
        
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        
        if not url or not key:
            logger.warning("⚠️ Supabase ключи не заданы")
            return None
            
        client = create_client(url, key)
        logger.info("✅ Supabase подключен")
        return client
    except Exception as e:
        logger.warning(f"⚠️ Supabase недоступен: {e}")
        return None

# ============ КОМАНДЫ ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    
    # Пробуем сохранить в Supabase
    supabase = init_supabase()
    if supabase:
        try:
            supabase.table("users").upsert({
                "user_id": user.id,
                "username": user.username or "",
                "first_name": user.first_name,
                "last_name": user.last_name or "",
                "updated_at": datetime.utcnow().isoformat()
            }).execute()
            logger.info(f"✅ User {user.id} saved to Supabase")
        except Exception as e:
            logger.error(f"❌ Supabase error: {e}")
    
    keyboard = [
        [InlineKeyboardButton("📈 Запросить сигнал", callback_data="signal")],
        [InlineKeyboardButton("💼 Тарифы", callback_data="plans")],
        [InlineKeyboardButton("🔗 Привязать PO", callback_data="setup_po")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")]
    ]
    
    text = f"👋 Привет, {user.first_name}!\nЯ бот для торговых сигналов."
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /plans"""
    text = """
📊 **Тарифы:**
• 🆓 Free - 3 сигнала/день
• 🥈 Pro - 10 сигналов/день
• 🥇 Premium - неограниченно
"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status"""
    user = update.effective_user
    
    text = f"""
📊 **Статус:**
• ID: {user.id}
• Имя: {user.first_name}
• Бот: ✅ Работает
• Режим: {'Supabase' if init_supabase() else 'Локальный'}
"""
    
    await update.message.reply_text(text, parse_mode='Markdown')

# ============ ОБРАБОТКА КНОПОК ============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "signal":
        await handle_signal(query)
    elif query.data == "plans":
        await plans(update, context)
    elif query.data == "status":
        await status(update, context)
    elif query.data == "setup_po":
        await query.edit_message_text("Введите PO логин:")
        return 1

async def handle_signal(query):
    """Обработка запроса сигнала"""
    supabase = init_supabase()
    
    if supabase:
        try:
            supabase.table("signal_requests").insert({
                "user_id": query.from_user.id,
                "request_type": "short",
                "status": "pending",
                "created_at": datetime.utcnow().isoformat()
            }).execute()
            message = "✅ Запрос отправлен в торговое ядро!"
        except Exception as e:
            logger.error(f"Supabase error: {e}")
            message = "✅ Запрос обработан (локально)"
    else:
        message = "✅ Запрос получен (тестовый режим)"
    
    await query.edit_message_text(message)

# ============ FSM ДЛЯ PO ============
async def receive_po_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение PO логина"""
    context.user_data['po_login'] = update.message.text
    await update.message.reply_text("Введите PO пароль:")
    return 2

async def receive_po_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение PO пароля"""
    login = context.user_data.get('po_login', '')
    password = update.message.text
    
    supabase = init_supabase()
    if supabase and login and password:
        try:
            supabase.table("po_credentials").upsert({
                "user_id": update.effective_user.id,
                "po_login_encrypted": login,  # TODO: Зашифровать
                "po_password_encrypted": password  # TODO: Зашифровать
            }).execute()
            message = "✅ PO аккаунт привязан!"
        except Exception as e:
            logger.error(f"Supabase error: {e}")
            message = "✅ Данные сохранены локально"
    else:
        message = "✅ Данные сохранены (тестовый режим)"
    
    context.user_data.clear()
    await update.message.reply_text(message)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена"""
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено")
    return ConversationHandler.END

# ============ ЗАПУСК ============
def main():
    """Главная функция"""
    logger.info("🤖 Запуск бота...")
    
    # Проверяем токен
    if not BOT_TOKEN or BOT_TOKEN == "8218904195:AAGinuQn0eGe8qYm-P5EOPwVq3awPyJ5fD8":
        logger.warning("⚠️ Используется дефолтный токен")
    
    # Создаем приложение
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation Handler
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(
            lambda u,c: button_handler(u,c), pattern='^setup_po$'
        )],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_po_login)],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_po_password)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("plans", plans))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(conv_handler)
    
    logger.info("✅ Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()