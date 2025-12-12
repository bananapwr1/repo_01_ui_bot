"""main.py (Repo 01 UI Bot)

ТЗ (критично):
- Локальная SQLite для пользовательских профилей/состояний/админки/банов.
- Supabase (только публичный ключ) — только для внешних таблиц (например, signal_requests).
- Сложный UI/UX: меню/навигация через inline-кнопки, Back/Home всегда доступны.
- "Умный" интерфейс: удаляем предыдущее UI-сообщение перед отправкой нового.
- Мультиязычность (i18n).
- Удалён YooKassa; добавлены заглушки крипто-платежей.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from telegram import (
    BotCommand,
    BotCommandScopeChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from crypto_utils import encrypt_ssid
from payments import check_crypto_payment_status, create_crypto_payment
from supabase import Client, create_client
from user_db_handler import (
    ensure_user,
    get_encrypted_data_from_local_db,
    get_user_profile,
    get_user_state,
    init_db,
    reset_user_data,
    save_encrypted_credentials,
    set_user_state,
    update_user_profile,
)


load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Env ---
TELEGRAM_BOT_TOKEN_UI = os.getenv("TELEGRAM_BOT_TOKEN_UI")
SUPABASE_URL = os.getenv("SUPABASE_URL")
# ТЗ: SUPABASE_KEY (публичный ключ). Оставляем fallback на старое имя для совместимости.
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")

ADMIN_USER_ID: Optional[int]
try:
    ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "").strip() or "0") or None
except Exception:
    ADMIN_USER_ID = None


def _is_root_admin(user_id: int) -> bool:
    return bool(ADMIN_USER_ID) and user_id == ADMIN_USER_ID


# --- Supabase client (optional) ---
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("✅ Supabase client initialized")
    except Exception as e:
        logger.error(f"❌ Supabase init failed: {e}")
        supabase = None


# --- Local DB ---
init_db()


# --- i18n ---
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "ru": {
        "banned": "🚫 Доступ ограничен. Обратитесь к администратору.",
        "home_title": "🏠 Главный экран",
        "home_profile": (
            "<b>Профиль</b>\n"
            "ID: <code>{user_id}</code>\n"
            "Язык: <b>{language}</b>\n"
            "Валюта: <b>{currency}</b>\n"
            "Тариф: <b>{plan}</b>\n"
            "PO: <b>{po_status}</b>\n"
        ),
        "po_set": "настроено",
        "po_not_set": "не настроено",
        "menu_title": "📋 Меню",
        "help_title": "❓ Помощь",
        "help_body": (
            "<b>Команды</b>\n"
            "/start — главный экран\n"
            "/help — помощь\n"
            "/bank — банк/оплата подписки\n"
            "/my_longs — мои Long\n"
            "/my_stats — моя статистика\n"
            "/plans — тарифы\n"
            "/settings — настройки\n\n"
            "<b>Сигналы</b>\n"
            "/long — запрос Long-сигнала\n"
            "/short — запрос Short-сигнала\n"
        ),
        "bank_title": "🏦 Банк",
        "bank_body": "Текущий тариф: <b>{plan}</b>\n\nВыберите подписку для оплаты:",
        "my_longs_title": "📈 Мои Long",
        "my_longs_empty": "Пока нет сохранённых Long-сигналов.",
        "my_stats_title": "📊 Моя статистика",
        "my_stats_body": "Статистика профиля отображается на главном экране.",
        "plans_title": "💳 Тарифы",
        "plans_body": "Ваш текущий тариф: <b>{plan}</b>\n\nВыберите тариф для апгрейда:",
        "settings_title": "⚙️ Настройки",
        "settings_body": "Язык: <b>{language}</b>\nВалюта: <b>{currency}</b>",
        "nav_back": "⬅️ Назад",
        "nav_home": "🏠 Домой",
        "btn_menu": "📋 Меню",
        "btn_signal": "📡 Сигнал",
        "btn_plans": "💳 Тарифы",
        "btn_settings": "⚙️ Настройки",
        "btn_set_po": "🔐 Настроить PO",
        "set_po_usage": "📝 Использование: /set_po <логин> <пароль>",
        "set_po_saved": "✅ Данные PO зашифрованы и сохранены локально.",
        "set_po_invalid": "❌ Проверьте логин/пароль (логин 3-100, пароль 6-100 символов).",
        "encryption_error": "❌ Ошибка шифрования. Попробуйте позже.",
        "db_error": "❌ Ошибка базы данных. Попробуйте позже.",
        "signal_requires_plan": "🔒 Запрос сигналов доступен на тарифе Long/Short/VIP. Откройте «Тарифы».",
        "signal_requires_plan_long": "🔒 Long-сигналы доступны на тарифе Long/VIP.",
        "signal_requires_plan_short": "🔒 Short-сигналы доступны на тарифе Short/VIP.",
        "signal_requires_po": "❌ Сначала настройте PO через /set_po.",
        "signal_sent": "⏳ Запрос на сигнал отправлен. Ожидайте ответ от ядра.",
        "signal_supabase_off": "⚠️ Supabase не настроен. Запрос сигналов временно недоступен.",
        "plan_free": "Free",
        "plan_pro": "Pro",
        "plan_long": "Long",
        "plan_short": "Short",
        "plan_vip": "VIP",
        "pay_created": (
            "💳 Создан крипто-платёж для тарифа <b>{plan}</b>\n"
            "Сумма: <b>{amount} {currency}</b>\n"
            "Payment ID: <code>{payment_id}</code>\n\n"
            "Ссылка на оплату: {pay_url}"
        ),
        "pay_check_pending": "⏳ Платёж пока не подтверждён. Попробуйте позже.",
        "pay_check_paid": "✅ Платёж подтверждён! Тариф обновлён на <b>{plan}</b>.",
        "admin_denied": "🚫 Команда доступна только ADMIN_USER_ID.",
        "admin_panel_title": "🛡️ <b>Admin Panel</b>",
        "admin_btn_ban": "🚫 Забанить пользователя",
        "admin_btn_unban": "✅ Разбанить пользователя",
        "admin_btn_set_plan": "💳 Выдать подписку пользователю",
        "admin_btn_reset": "♻️ Сбросить пользователя",
        "admin_btn_give_me": "🧪 Выдать себе подписку (тест)",
        "admin_prompt_ban": "Введите ID пользователя для бана:",
        "admin_prompt_unban": "Введите ID пользователя для разбана:",
        "admin_prompt_reset": "Введите ID пользователя для сброса:",
        "admin_prompt_set_plan": "Введите: <code>user_id plan</code>\nПример: <code>123456789 vip</code>\nДоступные: free, long, short, vip",
        "admin_bad_input": "❌ Неверный формат. Попробуйте ещё раз.",
        "admin_help": (
            "🛡️ <b>Admin</b>\n"
            "/ban_user <id>\n"
            "/unban_user <id>\n"
            "/add_admin <id>\n"
            "/remove_admin <id>\n"
            "/reset_user <id>"
        ),
        "admin_done": "✅ Готово.",
        "admin_bad_args": "❌ Неверные аргументы. Пример: /ban_user 123456",
        "god_done": "✅ VIP-статус и права администратора выданы бессрочно.",
    },
    "en": {
        "banned": "🚫 Access restricted. Contact support.",
        "home_title": "🏠 Home",
        "home_profile": (
            "<b>Profile</b>\n"
            "ID: <code>{user_id}</code>\n"
            "Language: <b>{language}</b>\n"
            "Currency: <b>{currency}</b>\n"
            "Plan: <b>{plan}</b>\n"
            "PO: <b>{po_status}</b>\n"
        ),
        "po_set": "configured",
        "po_not_set": "not configured",
        "menu_title": "📋 Menu",
        "help_title": "❓ Help",
        "help_body": (
            "<b>Commands</b>\n"
            "/start — home\n"
            "/help — help\n"
            "/bank — bank/subscription payments\n"
            "/my_longs — my Longs\n"
            "/my_stats — my stats\n"
            "/plans — plans\n"
            "/settings — settings\n\n"
            "<b>Signals</b>\n"
            "/long — request Long signal\n"
            "/short — request Short signal\n"
        ),
        "bank_title": "🏦 Bank",
        "bank_body": "Current plan: <b>{plan}</b>\n\nChoose a subscription to pay:",
        "my_longs_title": "📈 My Longs",
        "my_longs_empty": "No saved Long signals yet.",
        "my_stats_title": "📊 My stats",
        "my_stats_body": "Profile stats are shown on the Home screen.",
        "plans_title": "💳 Plans",
        "plans_body": "Current plan: <b>{plan}</b>\n\nChoose a plan to upgrade:",
        "settings_title": "⚙️ Settings",
        "settings_body": "Language: <b>{language}</b>\nCurrency: <b>{currency}</b>",
        "nav_back": "⬅️ Back",
        "nav_home": "🏠 Home",
        "btn_menu": "📋 Menu",
        "btn_signal": "📡 Signal",
        "btn_plans": "💳 Plans",
        "btn_settings": "⚙️ Settings",
        "btn_set_po": "🔐 Configure PO",
        "set_po_usage": "Usage: /set_po <login> <password>",
        "set_po_saved": "✅ PO credentials encrypted & saved locally.",
        "set_po_invalid": "❌ Check login/password length.",
        "encryption_error": "❌ Encryption error. Try again later.",
        "db_error": "❌ Database error. Try again later.",
        "signal_requires_plan": "🔒 Signals require Long/Short/VIP. Open Plans.",
        "signal_requires_plan_long": "🔒 Long signals require Long/VIP.",
        "signal_requires_plan_short": "🔒 Short signals require Short/VIP.",
        "signal_requires_po": "❌ Configure PO first via /set_po.",
        "signal_sent": "⏳ Signal request sent. Please wait.",
        "signal_supabase_off": "⚠️ Supabase not configured. Signals are unavailable.",
        "plan_free": "Free",
        "plan_pro": "Pro",
        "plan_long": "Long",
        "plan_short": "Short",
        "plan_vip": "VIP",
        "pay_created": (
            "💳 Crypto payment created for <b>{plan}</b>\n"
            "Amount: <b>{amount} {currency}</b>\n"
            "Payment ID: <code>{payment_id}</code>\n\n"
            "Pay URL: {pay_url}"
        ),
        "pay_check_pending": "⏳ Payment is still pending. Try later.",
        "pay_check_paid": "✅ Payment confirmed! Plan updated to <b>{plan}</b>.",
        "admin_denied": "🚫 This command is restricted to ADMIN_USER_ID.",
        "admin_panel_title": "🛡️ <b>Admin Panel</b>",
        "admin_btn_ban": "🚫 Ban user",
        "admin_btn_unban": "✅ Unban user",
        "admin_btn_set_plan": "💳 Set user plan",
        "admin_btn_reset": "♻️ Reset user",
        "admin_btn_give_me": "🧪 Give me a plan (test)",
        "admin_prompt_ban": "Send target user ID to ban:",
        "admin_prompt_unban": "Send target user ID to unban:",
        "admin_prompt_reset": "Send target user ID to reset:",
        "admin_prompt_set_plan": "Send: <code>user_id plan</code>\nExample: <code>123456789 vip</code>\nAllowed: free, long, short, vip",
        "admin_bad_input": "❌ Invalid format. Try again.",
        "admin_help": (
            "🛡️ <b>Admin</b>\n"
            "/ban_user <id>\n"
            "/unban_user <id>\n"
            "/add_admin <id>\n"
            "/remove_admin <id>\n"
            "/reset_user <id>"
        ),
        "admin_done": "✅ Done.",
        "admin_bad_args": "❌ Bad args. Example: /ban_user 123456",
        "god_done": "✅ VIP access and admin privileges granted permanently.",
    },
}


def tr(lang: str, key: str, **kwargs: Any) -> str:
    table = TRANSLATIONS.get(lang) or TRANSLATIONS["ru"]
    template = table.get(key) or TRANSLATIONS["ru"].get(key) or key
    try:
        return template.format(**kwargs)
    except Exception:
        return template


# --- UI helpers ---
async def _ensure_not_banned(user_id: int) -> bool:
    profile = await get_user_profile(user_id)
    if profile.get("is_banned") and not _is_root_admin(user_id):
        return False
    return True


async def _delete_message_safe(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def send_ui(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup] = None,
) -> None:
    """Удаляет предыдущее UI-сообщение и отправляет новое."""
    profile = await get_user_profile(user_id)
    last_chat_id = profile.get("last_ui_chat_id")
    last_message_id = profile.get("last_ui_message_id")

    if last_chat_id and last_message_id:
        await _delete_message_safe(context, int(last_chat_id), int(last_message_id))

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
    await update_user_profile(user_id, last_ui_chat_id=chat_id, last_ui_message_id=msg.message_id)


async def _nav_stack(user_id: int) -> list[str]:
    stack = await get_user_state(user_id, "nav_stack", default=[])
    return stack if isinstance(stack, list) else []


async def _current_screen(user_id: int) -> str:
    cur = await get_user_state(user_id, "current_screen", default="home")
    return cur if isinstance(cur, str) else "home"


async def show_screen(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    screen: str,
    push_current: bool = True,
    clear_stack: bool = False,
) -> None:
    await ensure_user(user_id)

    if not await _ensure_not_banned(user_id):
        profile = await get_user_profile(user_id)
        await send_ui(
            context=context,
            user_id=user_id,
            chat_id=chat_id,
            text=tr(profile.get("language", "ru"), "banned"),
            keyboard=None,
        )
        return

    if clear_stack:
        await set_user_state(user_id, "nav_stack", [])

    cur = await _current_screen(user_id)
    if push_current and screen != cur:
        stack = await _nav_stack(user_id)
        stack.append(cur)
        await set_user_state(user_id, "nav_stack", stack[-20:])

    await set_user_state(user_id, "current_screen", screen)

    text, kb = await render_screen(user_id=user_id, screen=screen)
    await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=text, keyboard=kb)


def _nav_kb(lang: str, show_back: bool, show_home: bool) -> list[list[InlineKeyboardButton]]:
    row: list[InlineKeyboardButton] = []
    if show_back:
        row.append(InlineKeyboardButton(tr(lang, "nav_back"), callback_data="nav:back"))
    if show_home:
        row.append(InlineKeyboardButton(tr(lang, "nav_home"), callback_data="nav:home"))
    return [row] if row else []


async def render_screen(*, user_id: int, screen: str) -> tuple[str, InlineKeyboardMarkup]:
    profile = await get_user_profile(user_id)
    lang = profile.get("language", "ru")
    plan = profile.get("plan", "free")

    stack = await _nav_stack(user_id)
    show_back = len(stack) > 0 and screen != "home"
    show_home = screen != "home"

    if screen == "home":
        creds = await get_encrypted_data_from_local_db(user_id)
        po_status = tr(lang, "po_set") if creds else tr(lang, "po_not_set")

        text = f"<b>{tr(lang, 'home_title')}</b>\n\n" + tr(
            lang,
            "home_profile",
            user_id=user_id,
            language=profile.get("language", "ru"),
            currency=profile.get("currency", "USD"),
            plan=plan,
            po_status=po_status,
        )

        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(tr(lang, "btn_menu"), callback_data="nav:menu")],
                [InlineKeyboardButton(tr(lang, "btn_signal"), callback_data="action:signal")],
                [InlineKeyboardButton(tr(lang, "btn_plans"), callback_data="nav:plans")],
                [InlineKeyboardButton(tr(lang, "btn_settings"), callback_data="nav:settings")],
            ]
        )
        return text, kb

    if screen == "menu":
        text = f"<b>{tr(lang, 'menu_title')}</b>"
        kb_rows = [
            [InlineKeyboardButton(tr(lang, "btn_signal"), callback_data="action:signal")],
            [InlineKeyboardButton(tr(lang, "help_title"), callback_data="nav:help")],
            [InlineKeyboardButton(tr(lang, "bank_title"), callback_data="nav:bank")],
            [InlineKeyboardButton(tr(lang, "btn_plans"), callback_data="nav:plans")],
            [InlineKeyboardButton(tr(lang, "btn_settings"), callback_data="nav:settings")],
        ]
        kb_rows.extend(_nav_kb(lang, show_back, show_home))
        return text, InlineKeyboardMarkup(kb_rows)

    if screen == "help":
        text = f"<b>{tr(lang, 'help_title')}</b>\n\n" + tr(lang, "help_body")
        kb_rows: list[list[InlineKeyboardButton]] = []
        kb_rows.extend(_nav_kb(lang, show_back, show_home))
        return text, InlineKeyboardMarkup(kb_rows)

    if screen == "bank":
        text = f"<b>{tr(lang, 'bank_title')}</b>\n\n" + tr(lang, "bank_body", plan=plan)
        kb_rows = [
            [InlineKeyboardButton(tr(lang, "plan_long"), callback_data="plan:select:long")],
            [InlineKeyboardButton(tr(lang, "plan_short"), callback_data="plan:select:short")],
            [InlineKeyboardButton(tr(lang, "plan_vip"), callback_data="plan:select:vip")],
            [InlineKeyboardButton(tr(lang, "btn_plans"), callback_data="nav:plans")],
        ]
        kb_rows.extend(_nav_kb(lang, show_back, show_home))
        return text, InlineKeyboardMarkup(kb_rows)

    if screen == "my_longs":
        text = f"<b>{tr(lang, 'my_longs_title')}</b>\n\n" + tr(lang, "my_longs_empty")
        kb_rows: list[list[InlineKeyboardButton]] = []
        kb_rows.extend(_nav_kb(lang, show_back, show_home))
        return text, InlineKeyboardMarkup(kb_rows)

    if screen == "my_stats":
        text = f"<b>{tr(lang, 'my_stats_title')}</b>\n\n" + tr(lang, "my_stats_body")
        kb_rows: list[list[InlineKeyboardButton]] = []
        kb_rows.extend(_nav_kb(lang, show_back, show_home))
        return text, InlineKeyboardMarkup(kb_rows)

    if screen == "plans":
        text = f"<b>{tr(lang, 'plans_title')}</b>\n\n" + tr(lang, "plans_body", plan=plan)
        kb_rows = [
            [InlineKeyboardButton(tr(lang, "plan_free"), callback_data="plan:select:free")],
            [InlineKeyboardButton(tr(lang, "plan_long"), callback_data="plan:select:long")],
            [InlineKeyboardButton(tr(lang, "plan_short"), callback_data="plan:select:short")],
            [InlineKeyboardButton(tr(lang, "plan_vip"), callback_data="plan:select:vip")],
        ]
        kb_rows.extend(_nav_kb(lang, show_back, show_home))
        return text, InlineKeyboardMarkup(kb_rows)

    if screen == "settings":
        text = f"<b>{tr(lang, 'settings_title')}</b>\n\n" + tr(
            lang, "settings_body", language=profile.get("language", "ru"), currency=profile.get("currency", "USD")
        )
        kb_rows = [
            [
                InlineKeyboardButton("RU", callback_data="set:lang:ru"),
                InlineKeyboardButton("EN", callback_data="set:lang:en"),
            ],
            [
                InlineKeyboardButton("USD", callback_data="set:currency:USD"),
                InlineKeyboardButton("EUR", callback_data="set:currency:EUR"),
                InlineKeyboardButton("RUB", callback_data="set:currency:RUB"),
            ],
        ]
        kb_rows.extend(_nav_kb(lang, show_back, show_home))
        return text, InlineKeyboardMarkup(kb_rows)

    # fallback
    text = f"<b>{tr(lang, 'home_title')}</b>"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(lang, "nav_home"), callback_data="nav:home")]])
    return text, kb


# --- Supabase integration (external) ---
async def create_signal_request(user_id: int, request_type: str = "latest_signal") -> bool:
    if not supabase:
        return False
    # Внешние данные (не профиль пользователя)
    supabase.table("signal_requests").insert(
        {"user_id": user_id, "request_type": request_type, "status": "pending"}
    ).execute()
    return True


# --- FastAPI (core <-> UI bot) ---
api_app = FastAPI(
    title="UI Bot API for Trading Core",
    description="API для связи UI-бота с Ядром Анализа",
    version="1.1.0",
)


class CoreRequest(BaseModel):
    user_id: int
    request_source: str


@api_app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "UI Bot API",
        "version": "1.1.0",
        "endpoints": {"health": "/health", "credentials": "/get_po_credentials"},
    }


@api_app.get("/health")
async def health_check() -> Dict[str, Any]:
    supabase_status = "not_configured"
    if supabase:
        try:
            supabase.table("signal_requests").select("id").limit(1).execute()
            supabase_status = "connected"
        except Exception as e:
            logger.error(f"Supabase health check failed: {e}")
            supabase_status = "disconnected"

    return {
        "status": "healthy",
        "telegram_bot": "configured" if TELEGRAM_BOT_TOKEN_UI else "not_configured",
        "supabase": supabase_status,
        "encryption": "enabled" if os.getenv("ENCRYPTION_KEY") else "not_configured",
        "sqlite_db": "enabled",
    }


@api_app.post("/get_po_credentials")
async def get_po_credentials_endpoint(request_data: CoreRequest) -> Dict[str, Any]:
    user_id = request_data.user_id
    request_source = request_data.request_source

    logger.info(f"📥 Credential request for user {user_id} from {request_source}")

    if request_source not in ["trading_core", "render_core", "admin"]:
        raise HTTPException(status_code=403, detail="Unknown request source")

    encrypted_creds = await get_encrypted_data_from_local_db(user_id)
    if not encrypted_creds:
        raise HTTPException(status_code=404, detail=f"Credentials not found for user {user_id}")

    return {
        "status": "success",
        "user_id": user_id,
        "login_enc": encrypted_creds["login_enc"],
        "password_enc": encrypted_creds["password_enc"],
    }


# --- Telegram commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await ensure_user(user_id)
    if _is_root_admin(user_id):
        await update_user_profile(user_id, is_admin=1)

    chat_id = update.effective_chat.id

    # Удаляем команду /start для "чистого" UI
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)

    await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="home", push_current=False, clear_stack=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="help")


async def bank_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="bank")


async def my_longs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="my_longs")


async def my_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    # ТЗ: главная статистика — на домашнем экране
    await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="home", push_current=False)


async def long_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    await _handle_signal(user_id=user_id, chat_id=chat_id, context=context, request_type="long")


async def short_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    await _handle_signal(user_id=user_id, chat_id=chat_id, context=context, request_type="short")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="menu")


async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="plans")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="settings")


async def set_po_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    profile = await get_user_profile(user_id)
    lang = profile.get("language", "ru")

    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)

    if not context.args or len(context.args) != 2:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "set_po_usage"))
        return

    login, password = context.args[0], context.args[1]
    if len(login) < 3 or len(login) > 100 or len(password) < 6 or len(password) > 100:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "set_po_invalid"))
        return

    login_enc = encrypt_ssid(login)
    password_enc = encrypt_ssid(password)
    if not login_enc or not password_enc:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "encryption_error"))
        return

    try:
        await save_encrypted_credentials(user_id, login_enc, password_enc)
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "set_po_saved"))
    except Exception as e:
        logger.error(f"DB error saving credentials for user {user_id}: {e}")
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "db_error"))


async def request_signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)
    await _handle_signal(user_id=user_id, chat_id=chat_id, context=context)


# --- Callback handler ---
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else user_id

    try:
        await query.answer()
    except Exception:
        pass

    data = query.data or ""

    # Удаляем сообщение, по которому кликнули (доп. чистота UI)
    if query.message:
        await _delete_message_safe(context, chat_id, query.message.message_id)

    if data == "nav:home":
        await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="home", push_current=False, clear_stack=True)
        return

    if data == "nav:back":
        stack = await _nav_stack(user_id)
        if stack:
            prev = stack.pop()
            await set_user_state(user_id, "nav_stack", stack)
            await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen=prev, push_current=False)
        else:
            await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="home", push_current=False, clear_stack=True)
        return

    if data.startswith("nav:"):
        screen = data.split(":", 1)[1]
        if screen in {"menu", "plans", "settings", "home", "help", "bank", "my_longs", "my_stats"}:
            await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen=screen)
        return

    if data == "action:signal":
        await _handle_signal(user_id=user_id, chat_id=chat_id, context=context, request_type="latest_signal")
        return

    if data.startswith("set:lang:"):
        lang = data.split(":", 2)[2]
        if lang in TRANSLATIONS:
            await update_user_profile(user_id, language=lang)
        await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="settings", push_current=False)
        return

    if data.startswith("set:currency:"):
        currency = data.split(":", 2)[2]
        if currency in {"USD", "EUR", "RUB"}:
            await update_user_profile(user_id, currency=currency)
        await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="settings", push_current=False)
        return

    if data.startswith("admin:"):
        profile = await get_user_profile(user_id)
        lang = profile.get("language", "ru")

        if not _is_root_admin(user_id):
            await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_denied"))
            return

        if data.startswith("admin:give:"):
            plan = data.split(":", 2)[2].strip().lower()
            if plan in {"long", "short", "vip"}:
                await update_user_profile(user_id, plan=plan, is_admin=1, is_banned=0)
                await set_user_state(user_id, "admin_flow", None)
                await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_done"))
                await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="home", push_current=False, clear_stack=True)
            return

        if data.startswith("admin:flow:"):
            action = data.split(":", 2)[2].strip()
            await set_user_state(user_id, "admin_flow", {"action": action})
            prompt_key = {
                "ban": "admin_prompt_ban",
                "unban": "admin_prompt_unban",
                "reset": "admin_prompt_reset",
                "set_plan": "admin_prompt_set_plan",
            }.get(action, "admin_bad_input")
            await send_ui(
                context=context,
                user_id=user_id,
                chat_id=chat_id,
                text=tr(lang, prompt_key),
                keyboard=InlineKeyboardMarkup(_nav_kb(lang, show_back=False, show_home=True)),
            )
            return

    if data.startswith("plan:select:"):
        plan = data.split(":", 2)[2]
        profile = await get_user_profile(user_id)
        lang = profile.get("language", "ru")

        if plan == "free":
            await update_user_profile(user_id, plan="free")
            await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="plans", push_current=False)
            return

        plan = str(plan).lower()
        if plan not in {"long", "short", "vip"}:
            await show_screen(context=context, user_id=user_id, chat_id=chat_id, screen="plans", push_current=False)
            return

        amount = 10.0 if plan in {"long", "short"} else 25.0
        payment = create_crypto_payment(user_id=user_id, plan=plan, amount=amount, currency="USDT")
        await set_user_state(
            user_id,
            "pending_payment",
            {"payment_id": payment.payment_id, "plan": plan, "amount": amount, "currency": payment.currency},
        )

        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ I paid / Проверить", callback_data=f"plan:check:{payment.payment_id}")],
                *(_nav_kb(lang, show_back=True, show_home=True)),
            ]
        )
        await send_ui(
            context=context,
            user_id=user_id,
            chat_id=chat_id,
            text=tr(
                lang,
                "pay_created",
                plan=plan.upper(),
                amount=amount,
                currency=payment.currency,
                payment_id=payment.payment_id,
                pay_url=payment.pay_url,
            ),
            keyboard=kb,
        )
        return

    if data.startswith("plan:check:"):
        payment_id = data.split(":", 2)[2]
        pending = await get_user_state(user_id, "pending_payment", default=None)
        profile = await get_user_profile(user_id)
        lang = profile.get("language", "ru")

        status = check_crypto_payment_status(payment_id)
        if status == "paid" and isinstance(pending, dict) and pending.get("payment_id") == payment_id:
            plan = pending.get("plan", "pro")
            await update_user_profile(user_id, plan=plan)
            await set_user_state(user_id, "pending_payment", None)
            await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "pay_check_paid", plan=plan.upper()))
        else:
            await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "pay_check_pending"))
        return


async def _handle_signal(*, user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = await get_user_profile(user_id)
    lang = profile.get("language", "ru")
    plan = profile.get("plan", "free")

    if plan not in {"pro", "vip"}:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "signal_requires_plan"))
        return

    creds = await get_encrypted_data_from_local_db(user_id)
    if not creds:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "signal_requires_po"))
        return

    if not supabase:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "signal_supabase_off"))
        return

    try:
        await asyncio.to_thread(lambda: None)  # микроyield для гладкости UI
        ok = await create_signal_request(user_id)
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "signal_sent" if ok else "signal_supabase_off"))
    except Exception as e:
        logger.error(f"Signal request error for user {user_id}: {e}")
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "signal_supabase_off"))


# --- Admin commands (root-only) ---
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    profile = await get_user_profile(user_id)
    lang = profile.get("language", "ru")

    if not _is_root_admin(user_id):
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_denied"))
        return

    if update.message:
        await _delete_message_safe(context, chat_id, update.message.message_id)

    await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_help"))


def _parse_target_id(context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    try:
        if not context.args:
            return None
        return int(str(context.args[0]).strip())
    except Exception:
        return None


async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    profile = await get_user_profile(user_id)
    lang = profile.get("language", "ru")

    if not _is_root_admin(user_id):
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_denied"))
        return

    target_id = _parse_target_id(context)
    if not target_id:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_bad_args"))
        return

    await ensure_user(target_id)
    await update_user_profile(target_id, is_banned=1)
    await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_done"))


async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    profile = await get_user_profile(user_id)
    lang = profile.get("language", "ru")

    if not _is_root_admin(user_id):
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_denied"))
        return

    target_id = _parse_target_id(context)
    if not target_id:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_bad_args"))
        return

    await ensure_user(target_id)
    await update_user_profile(target_id, is_banned=0)
    await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_done"))


async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    profile = await get_user_profile(user_id)
    lang = profile.get("language", "ru")

    if not _is_root_admin(user_id):
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_denied"))
        return

    target_id = _parse_target_id(context)
    if not target_id:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_bad_args"))
        return

    await ensure_user(target_id)
    await update_user_profile(target_id, is_admin=1)
    await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_done"))


async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    profile = await get_user_profile(user_id)
    lang = profile.get("language", "ru")

    if not _is_root_admin(user_id):
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_denied"))
        return

    target_id = _parse_target_id(context)
    if not target_id:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_bad_args"))
        return

    await ensure_user(target_id)
    await update_user_profile(target_id, is_admin=0)
    await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_done"))


async def reset_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    profile = await get_user_profile(user_id)
    lang = profile.get("language", "ru")

    if not _is_root_admin(user_id):
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_denied"))
        return

    target_id = _parse_target_id(context)
    if not target_id:
        await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_bad_args"))
        return

    await reset_user_data(target_id)
    await send_ui(context=context, user_id=user_id, chat_id=chat_id, text=tr(lang, "admin_done"))


# --- Runner ---
async def run_telegram_bot(application: Application) -> None:
    logger.info("🚀 Starting Telegram bot...")

    # Если на стороне Telegram остался webhook (частая причина "бот запущен, но polling не получает апдейты"),
    # то принудительно снимаем его перед polling.
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook disabled (polling mode)")
    except Exception as e:
        # Не фейлим старт целиком: иногда delete_webhook может падать из-за сетевых/временных проблем.
        logger.warning(f"⚠️ Could not delete webhook (continuing): {e}")

    await application.initialize()
    await application.start()
    await application.updater.start_polling(
        poll_interval=1.0,
        timeout=10,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

    try:
        while True:
            await asyncio.sleep(60)
    finally:
        logger.info("🛑 Stopping Telegram bot...")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


async def main() -> None:
    logger.info("=" * 60)
    logger.info("🚀 Starting UI Bot (Telegram + API)")
    logger.info("=" * 60)

    if not TELEGRAM_BOT_TOKEN_UI:
        raise ValueError("TELEGRAM_BOT_TOKEN_UI is required")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN_UI).build()

    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("plans", plans_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("set_po", set_po_command))
    application.add_handler(CommandHandler("signal", request_signal_command))

    # Admin
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("ban_user", ban_user_command))
    application.add_handler(CommandHandler("unban_user", unban_user_command))
    application.add_handler(CommandHandler("add_admin", add_admin_command))
    application.add_handler(CommandHandler("remove_admin", remove_admin_command))
    application.add_handler(CommandHandler("reset_user", reset_user_command))

    # UI callbacks
    application.add_handler(CallbackQueryHandler(callback_router))

    telegram_task = asyncio.create_task(run_telegram_bot(application))

    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(api_app, host="0.0.0.0", port=port, log_level="info", access_log=True)
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())

    await asyncio.gather(telegram_task, api_task)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Stopped")
