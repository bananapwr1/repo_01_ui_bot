# crypto_utils.py
import os
from cryptography.fernet import Fernet
import logging

logger = logging.getLogger(__name__)

def get_fernet_key():
    """Получает ключ Fernet из переменной окружения."""
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        logger.error("ENCRYPTION_KEY не задан в переменных окружения!")
        raise ValueError("ENCRYPTION_KEY is not set")
    # Ключ должен быть закодирован в base64
    return Fernet(key.encode())

def encrypt_data(data: str) -> str:
    """Шифрует строку."""
    try:
        f = get_fernet_key()
        # Энкодируем данные, шифруем и декодируем результат в строку
        return f.encrypt(data.encode()).decode()
    except Exception as e:
        logger.error(f"Ошибка шифрования: {e}")
        return ""

def decrypt_data(encrypted_data: str) -> str:
    """Дешифрует строку."""
    try:
        f = get_fernet_key()
        # Энкодируем строку, дешифруем и декодируем результат
        return f.decrypt(encrypted_data.encode()).decode()
    except Exception as e:
        logger.error(f"Ошибка дешифрования: {e}")
        return ""

