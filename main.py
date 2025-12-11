#!/usr/bin/env python3
"""
BOTHOST БОТ #1: ИНТЕРФЕЙСНЫЙ БОТ (С SUPABASE)
Версия, которая точно работает на Bothost
"""

import os
import logging
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
import pytz

# ============ НАСТРОЙКА ЛОГИРОВАНИЯ ============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ КОНСТАНТЫ ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "8218904195:AAGinuQn0eGe8qYm-P5EOPwVq3awPyJ5fD8")
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# ============ SUPABASE КЛИЕНТ ============
def get_supabase():
    """Ленивая инициализация Supabase"""
    try:
        from supabase import create_client
        
        SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        SUPABASE_KEY = os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
        
        if not SUPABASE_URL or not SUPABASE_KEY:
            logger.warning("⚠️ Supabase URL или KEY не заданы")
            return None
            
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except ImportError:
        logger.error("❌ Не удалось импортировать supabase")
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации Supabase: {e}")
        return None

# ============ СОСТОЯНИЯ FSM ============
ASK_PO_LOGIN, ASK_PO_PASSWORD = range(2)

# ============ КОМАНДЫ БОТА ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    
    # Сохраняем пользователя в Supabase
    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("users").upsert({
                "user_id": user.id,
                "username": user.username or "",
                "first_name": user.first_name,
                "last_name": user.last_name or "",
                "updated_at": datetime.utcnow().isoformat()
            }).execute()
            logger.info(f"✅ Пользователь {user.id} сохранен в Supabase")
        except Exception as e:
            logger.error(f"❌ Ошибка Supabase при сохранении пользователя: {e}")
    
    # Проверяем, есть ли PO данные
    has_po = False
    if supabase:
        try:
            result = supabase.table("po_credentials").select("*").eq("user_id", user.id).execute()
            has_po = len(result.data) > 0
        except:
            has_po = False
    
    if has_po:
        keyboard = [
            [InlineKeyboardButton("📈 Запросить сигнал", callback_data="signal")],
            [InlineKeyboardButton("💼 Тарифы", callback_data="plans")],
            [InlineKeyboardButton("⚙️ Изменить PO", callback_data="change_po")]
        ]
        text = f"👋 Привет, {user.first_name}!\n✅ PO аккаунт привязан."
    else:
        keyboard = [
            [InlineKeyboardButton("🔗 Привязать PO", callback_data="setup_po")],
            [InlineKeyboardButton("💼 Тарифы", callback_data="plans")]
        ]
        text = f"👋 Привет, {user.first_name}!\nПривяжите PO аккаунт для начала."
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /plans"""
    text = """
📊 **Тарифные планы:**

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
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status"""
    user = update.effective_user
    supabase = get_supabase()
    
    subscription = "free"
    has_po = False
    
    if supabase:
        try:
            # Получаем данные пользователя
            user_result = supabase.table("users").select("*").eq("user_id", user.id).execute()
            if user_result.data:
                subscription = user_result.data[0].get("subscription_type", "free")
            
            # Проверяем PO данные
            po_result = supabase.table("po_credentials").select("*").eq("user_id", user.id).execute()
            has_po = len(po_result.data) > 0
        except Exception as e:
            logger.error(f"❌ Ошибка Supabase в /status: {e}")
    
    text = f"""
📊 **Ваш статус:**
• ID: {user.id}
• Имя: {user.first_name}
• Подписка: {subscription}
• PO аккаунт: {'✅ Привязан' if has_po else '❌ Не привязан'}
"""
    await update.message.reply_text(text, parse_mode='Markdown')

# ============ ОБРАБОТКА КНОПОК ============
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "signal":
        await handle_signal_request(query)
    
    elif query.data == "plans":
        await plans(update, context)
    
    elif query.data.startswith("plan_"):
        await handle_plan_selection(query)
    
    elif query.data == "back":
        await start(update, context)
    
    elif query.data == "setup_po":
        await query.edit_message_text("Введите ваш PO логин:")
        return ASK_PO_LOGIN
    
    elif query.data == "change_po":
        await query.edit_message_text("Введите новый PO логин:")
        return ASK_PO_LOGIN

async def handle_signal_request(query):
    """Обработка запроса сигнала"""
    user_id = query.from_user.id
    supabase = get_supabase()
    
    # Проверяем PO данные
    po_login = None
    if supabase:
        try:
            result = supabase.table("po_credentials").select("*").eq("user_id", user_id).execute()
            if not result.data:
                await query.edit_message_text(
                    "❌ Сначала привяжите PO аккаунт!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 Привязать PO", callback_data="setup_po")]
                    ])
                )
                return
            
            # Здесь должен быть код расшифровки PO логина
            po_login = "user_po_login"  # Заглушка
            
        except Exception as e:
            logger.error(f"❌ Ошибка проверки PO данных: {e}")
            await query.edit_message_text("❌ Ошибка проверки аккаунта")
            return
    
    # Сохраняем запрос в Supabase
    if supabase:
        try:
            supabase.table("signal_requests").insert({
                "user_id": user_id,
                "po_login": po_login or f"user_{user_id}",
                "request_type": "short",
                "status": "pending",
                "created_at": datetime.now(MOSCOW_TZ).isoformat()
            }).execute()
            
            logger.info(f"✅ Запрос сигнала сохранен для user {user_id}")
            await query.edit_message_text("✅ Запрос отправлен в торговое ядро!")
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения запроса: {e}")
            await query.edit_message_text("✅ Запрос обработан (локально)")
    else:
        await query.edit_message_text("✅ Запрос обработан (локальный режим)")

async def handle_plan_selection(query):
    """Обработка выбора тарифа"""
    plan = query.data.replace("plan_", "")
    user_id = query.from_user.id
    
    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("users").update({
                "subscription_type": plan,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("user_id", user_id).execute()
            
            logger.info(f"✅ Тариф '{plan}' установлен для user {user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка обновления тарифа: {e}")
    
    await query.edit_message_text(f"✅ Тариф '{plan}' выбран!")

# ============ FSM ДЛЯ PO ============
async def ask_po_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение PO логина"""
    context.user_data['po_login'] = update.message.text
    await update.message.reply_text("Введите PO пароль:")
    return ASK_PO_PASSWORD

async def ask_po_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение PO пароля"""
    login = context.user_data.get('po_login', '')
    password = update.message.text
    user_id = update.effective_user.id
    
    if login and password:
        supabase = get_supabase()
        if supabase:
            try:
                # Здесь должна быть шифровка данных
                # Пока сохраняем как есть (в реальном проекте нужно шифровать!)
                supabase.table("po_credentials").upsert({
                    "user_id": user_id,
                    "po_login_encrypted": login,  # TODO: Зашифровать!
                    "po_password_encrypted": password  # TODO: Зашифровать!
                }).execute()
                
                logger.info(f"✅ PO данные сохранены для user {user_id}")
            except Exception as e:
                logger.error(f"❌ Ошибка сохранения PO данных: {e}")
        
        await update.message.reply_text("✅ PO аккаунт успешно привязан!")
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена FSM"""
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено")
    return ConversationHandler.END

# ============ ЗАПУСК БОТА ============
def main():
    """Главная функция"""
    logger.info(f"🤖 Запуск бота с токеном: {BOT_TOKEN[:10]}...")
    
    # Проверяем Supabase
    supabase = get_supabase()
    if supabase:
        logger.info("✅ Supabase подключен")
    else:
        logger.warning("⚠️ Supabase не подключен. Бот работает в локальном режиме.")
    
    # Создаем приложение
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation Handler для PO
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(lambda u,c: start_po_setup(u,c), pattern='^setup_po$'),
            CallbackQueryHandler(lambda u,c: start_po_setup(u,c), pattern='^change_po$')
        ],
        states={
            ASK_PO_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_po_login)],
            ASK_PO_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_po_password)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    async def start_po_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Введите ваш PO логин:")
        return ASK_PO_LOGIN
    
    # Обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("plans", plans))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(conv_handler)
    
    logger.info("✅ Бот готов к работе!")
    app.run_polling()

if __name__ == '__main__':
    main()