"""
user_db_handler.py

Локальная SQLite-база для UI-бота (Repo 01).

Хранит:
- профиль пользователя (язык/валюта/тариф/бан/админ-флаг)
- состояния/навигацию (key-value, JSON)
- последний UI-message для "умного" удаления
- зашифрованные учетные данные (login/password/ssid)
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import sqlite3
import threading
from typing import Any, Dict, Optional


DB_PATH = os.getenv("UI_BOT_DB_PATH") or os.path.join(os.path.dirname(__file__), "ui_bot.sqlite3")
_DB_INIT_LOCK = threading.Lock()
_DB_INITIALIZED = False


def _utcnow_iso() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _connect() -> sqlite3.Connection:
    # timeout: helps with short bursts of concurrent writes
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # IMPORTANT: SQLite foreign keys are off by default
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    return conn


def init_db() -> None:
    """Создаёт таблицы SQLite (если их ещё нет)."""
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    with _DB_INIT_LOCK:
        if _DB_INITIALIZED:
            return

    conn = _connect()
    cur = conn.cursor()

    # Better concurrency characteristics for a bot workload
    try:
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        # Not fatal (e.g., some FS may not support WAL)
        pass

    # Профиль/флаги/последнее UI-сообщение
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            language TEXT NOT NULL DEFAULT 'ru',
            currency TEXT NOT NULL DEFAULT 'USD',
            plan TEXT NOT NULL DEFAULT 'free',
            is_admin INTEGER NOT NULL DEFAULT 0,
            is_banned INTEGER NOT NULL DEFAULT 0,
            last_ui_chat_id INTEGER,
            last_ui_message_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    # Зашифрованные секреты (только ciphertext)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_credentials (
            user_id INTEGER PRIMARY KEY,
            login_enc TEXT,
            password_enc TEXT,
            ssid_enc TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """
    )

    # Произвольные состояния (JSON value)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_states (
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, key),
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()
    conn.close()
    _DB_INITIALIZED = True


async def ensure_user(user_id: int) -> None:
    """Гарантирует, что запись пользователя существует."""
    init_db()

    def _op() -> None:
        now = _utcnow_iso()
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                """
                INSERT INTO users (user_id, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (user_id, now, now),
            )
        else:
            cur.execute("UPDATE users SET updated_at = ? WHERE user_id = ?", (now, user_id))
        conn.commit()
        conn.close()

    await asyncio.to_thread(_op)


async def get_user_profile(user_id: int) -> Dict[str, Any]:
    init_db()
    await ensure_user(user_id)

    def _op() -> Dict[str, Any]:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            # ensure_user должен был создать, но оставим безопасный fallback
            return {"user_id": user_id, "language": "ru", "currency": "USD", "plan": "free", "is_admin": 0, "is_banned": 0}
        return dict(row)

    return await asyncio.to_thread(_op)


async def update_user_profile(user_id: int, **fields: Any) -> None:
    """Обновляет поля профиля (language/currency/plan/is_admin/is_banned/last_ui_*)."""
    if not fields:
        return
    init_db()
    await ensure_user(user_id)

    allowed = {
        "language",
        "currency",
        "plan",
        "is_admin",
        "is_banned",
        "last_ui_chat_id",
        "last_ui_message_id",
    }
    safe_fields = {k: v for k, v in fields.items() if k in allowed}
    if not safe_fields:
        return

    def _op() -> None:
        now = _utcnow_iso()
        cols = ", ".join([f"{k} = ?" for k in safe_fields.keys()])
        params = list(safe_fields.values()) + [now, user_id]
        conn = _connect()
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {cols}, updated_at = ? WHERE user_id = ?", params)
        conn.commit()
        conn.close()

    await asyncio.to_thread(_op)


async def set_user_state(user_id: int, key: str, value: Any) -> None:
    init_db()
    await ensure_user(user_id)

    def _op() -> None:
        now = _utcnow_iso()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_states (user_id, key, value_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (user_id, key, json.dumps(value, ensure_ascii=False), now),
        )
        conn.commit()
        conn.close()

    await asyncio.to_thread(_op)


async def get_user_state(user_id: int, key: str, default: Any = None) -> Any:
    init_db()
    await ensure_user(user_id)

    def _op() -> Any:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT value_json FROM user_states WHERE user_id = ? AND key = ?", (user_id, key))
        row = cur.fetchone()
        conn.close()
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except Exception:
            return default

    return await asyncio.to_thread(_op)


async def delete_user_state(user_id: int, key: str) -> None:
    init_db()
    await ensure_user(user_id)

    def _op() -> None:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM user_states WHERE user_id = ? AND key = ?", (user_id, key))
        conn.commit()
        conn.close()

    await asyncio.to_thread(_op)


async def save_encrypted_credentials(user_id: int, login_enc: str, password_enc: str) -> None:
    """Совместимость: сохраняет (login/password) в таблицу user_credentials."""
    init_db()
    await ensure_user(user_id)

    def _op() -> None:
        now = _utcnow_iso()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_credentials (user_id, login_enc, password_enc, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                login_enc = excluded.login_enc,
                password_enc = excluded.password_enc,
                updated_at = excluded.updated_at
            """,
            (user_id, login_enc, password_enc, now),
        )
        conn.commit()
        conn.close()

    await asyncio.to_thread(_op)


async def save_encrypted_ssid(user_id: int, ssid_enc: str) -> None:
    init_db()
    await ensure_user(user_id)

    def _op() -> None:
        now = _utcnow_iso()
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_credentials (user_id, ssid_enc, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                ssid_enc = excluded.ssid_enc,
                updated_at = excluded.updated_at
            """,
            (user_id, ssid_enc, now),
        )
        conn.commit()
        conn.close()

    await asyncio.to_thread(_op)


async def get_encrypted_data_from_local_db(user_id: int) -> Optional[Dict[str, str]]:
    """Совместимость: получает зашифрованные данные для API-сервера."""
    init_db()
    await ensure_user(user_id)

    def _op() -> Optional[Dict[str, str]]:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT login_enc, password_enc FROM user_credentials WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row and row["login_enc"] and row["password_enc"]:
            return {"login_enc": row["login_enc"], "password_enc": row["password_enc"]}
        return None

    return await asyncio.to_thread(_op)


async def get_encrypted_ssid(user_id: int) -> Optional[str]:
    init_db()
    await ensure_user(user_id)

    def _op() -> Optional[str]:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT ssid_enc FROM user_credentials WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row and row["ssid_enc"]:
            return row["ssid_enc"]
        return None

    return await asyncio.to_thread(_op)


async def reset_user_data(user_id: int) -> None:
    """Удаляет локальные данные пользователя (профиль/креды/состояния)."""
    init_db()

    def _op() -> None:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM user_credentials WHERE user_id = ?", (user_id,))
        cur.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    await asyncio.to_thread(_op)

