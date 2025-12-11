# user_db_handler.py
import sqlite3
from typing import Optional, Dict

DATABASE_NAME = "user_credentials.db"

def init_db():
    """Инициализирует базу данных SQLite и создает таблицу."""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            login_enc TEXT NOT NULL,
            password_enc TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

async def save_encrypted_credentials(user_id: int, login_enc: str, password_enc: str):
    """Сохраняет или обновляет зашифрованные данные пользователя."""
    init_db()
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, login_enc, password_enc)
        VALUES (?, ?, ?)
    """, (user_id, login_enc, password_enc))
    conn.commit()
    conn.close()

async def get_encrypted_data_from_local_db(user_id: int) -> Optional[Dict[str, str]]:
    """Получает зашифрованные данные для API-сервера."""
    init_db()
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT login_enc, password_enc FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'login_enc': row[0],
            'password_enc': row[1]
        }
    return None

