#!/usr/bin/env python3
"""
БОТ #1: ИСПРАВЛЕННАЯ ВЕРСИЯ ДЛЯ BOTHOST
Совместимые версии библиотек
"""

import os
import logging
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

# ============ НАСТРОЙКА ЛОГИРОВАНИЯ ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# ============ ТОКЕН ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ============
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден в переменных окружения")
    sys.exit(1)

logger.info(f"✅ Токен получен: {BOT_TOKEN[:10]}...")

# ============ КОМАНДЫ БОТА ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    keyboard = [
        [InlineKeyboardButton("📈 Запросить сигнал", callback_data="signal")],
        [InlineKeyboardButton("💼 Тарифы", callback_data="plans")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")]
    ]
    
    await update.message.reply_text(
        f"👋 Привет, {update.effective_user.first_name}!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline-кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "signal":
        await query.edit_message_text("✅ Запрос отправлен в ядро!")
    elif query.data == "plans":
        await query.edit_message_text("🆓 Free\n🥈 Pro\n🥇 Premium")
    elif query.data == "status":
        await query.edit_message_text("✅ Бот работает\n📊 Статус: OK")

# ============ ЗАПУСК БОТА ============
def main():
    """Главная функция"""
    logger.info("🤖 Инициализация бота...")
    
    try:
        # Простая инициализация
        app = Application.builder().token(BOT_TOKEN).build()
        
        # Обработчики
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(button_handler))
        
        logger.info("✅ Бот инициализирован успешно!")
        logger.info("🚀 Запускаю polling...")
        
        app.run_polling(
            poll_interval=1.0,
            timeout=10,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == '__main__':
    main()