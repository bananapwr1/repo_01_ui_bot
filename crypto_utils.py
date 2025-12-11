# repo_01_ui_bot/crypto_utils.py
import os
from cryptography.fernet import Fernet
import logging
# ... (остальной код из 1.2. - нужен только get_fernet_key и encrypt_data) ...
# Добавьте функцию encrypt_data(data: str) -> str:
# ...
def encrypt_data(data: str, key_str: str) -> str:
    """Шифрует строку."""
    try:
        f = Fernet(key_str.encode())
        return f.encrypt(data.encode()).decode()
    except Exception as e:
        logger.error(f"Ошибка шифрования: {e}")
        raise
