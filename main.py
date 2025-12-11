#!/usr/bin/env python3
"""
БОТ #1: РАБОЧАЯ ВЕРСИЯ С FIXED HTTPX
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

# Токен бота - Bothost должен передать его
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не задан! Добавьте переменную окружения на Bothost.")
    # Используем дефолтный токен для тестирования
    BOT_TOKEN = "8218904195:AAGinuQn0eGe8qYm-P5EOPwVq3awPyJ5fD8"
    logger.warning(f"⚠️ Используется дефолтный токен: {BOT_TOKEN[:15]}...")

# ============ ОСНОВНЫЕ КОМАНДЫ ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    
    keyboard = [
        [InlineKeyboardButton("📈 Запросить сигнал", callback_data="signal")],
        [InlineKeyboardButton("💼 Тарифы", callback_data="plans")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")]
    ]
    
    text = f"👋 Привет, {user.first_name}!\nЯ бот для торговых сигналов.\n\nБот работает в тестовом режиме."
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /plans"""
    text = """
📊 **Тарифы:**

• 🆓 **Free** - 3 сигнала/день
• 🥈 **Pro** - 10 сигналов/день ($19/месяц)
• 🥇 **Premium** - неограниченно ($49/месяц)

Выберите тариф:
"""
    
    keyboard = [
        [InlineKeyboardButton("🆓 Free", callback_data="plan_free")],
        [InlineKeyboardButton("🥈 Pro", callback_data="plan_pro")],
        [InlineKeyboardButton("🥇 Premium", callback_data="plan_premium")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back")]
    ]
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status"""
    user = update.effective_user
    
    text = f"""
📊 **Статус:**

• ID: {user.id}
• Имя: {user.first_name}
• Бот: ✅ Работает
• Режим: Тестовый
• Версия: 1.0
"""
    
    await update.message.reply_text(text, parse_mode='Markdown')

# ============ ОБРАБОТКА КНОПОК ============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline-кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "signal":
        await query.edit_message_text("✅ Запрос отправлен в торговое ядро!\n\nСигнал будет готов через 1-2 минуты.")
    
    elif query.data == "plans":
        await plans(update, context)
    
    elif query.data == "status":
        await query.edit_message_text("📊 Статус: ✅ Работает\nРежим: Тестовый\nSupabase: ⏳ Настройка")
    
    elif query.data.startswith("plan_"):
        plan = query.data.replace("plan_", "")
        plans_map = {
            "free": "🆓 Free",
            "pro": "🥈 Pro", 
            "premium": "🥇 Premium"
        }
        await query.edit_message_text(f"✅ Выбран тариф: {plans_map.get(plan, plan)}")
    
    elif query.data == "back":
        await start(update, context)

# ============ ЗАПУСК БОТА ============
def main():
    """Главная функция запуска бота"""
    logger.info("🤖 Запуск бота #1...")
    
    try:
        # Создаем приложение с явным указанием request
        from telegram.request import HTTPXRequest
        
        app = Application.builder() \
            .token(BOT_TOKEN) \
            .request(HTTPXRequest()) \
            .build()
        
        # Добавляем обработчики
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("plans", plans))
        app.add_handler(CommandHandler("status", status))
        app.add_handler(CallbackQueryHandler(button_handler))
        
        logger.info("✅ Бот успешно инициализирован!")
        logger.info("🚀 Бот запущен и готов к работе!")
        
        # Запускаем polling
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    main()