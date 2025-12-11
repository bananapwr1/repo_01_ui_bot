# crypto_utils.py
import os
from cryptography.fernet import Fernet
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def get_encryption_key() -> str:
    """Получает ключ шифрования из переменных окружения."""
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        logger.error("🚫 ENCRYPTION_KEY не установлен в переменных окружения!")
        raise ValueError("ENCRYPTION_KEY is required")
    return key

def encrypt_data(data: str) -> str:
    """Шифрует строку используя ключ из переменных окружения."""
    try:
        key = get_encryption_key()
        f = Fernet(key.encode())
        encrypted = f.encrypt(data.encode()).decode()
        return encrypted
    except Exception as e:
        logger.error(f"❌ Ошибка шифрования: {e}")
        return None

def decrypt_data(encrypted_data: str) -> str:
    """Расшифровывает строку используя ключ из переменных окружения."""
    try:
        key = get_encryption_key()
        f = Fernet(key.encode())
        decrypted = f.decrypt(encrypted_data.encode()).decode()
        return decrypted
    except Exception as e:
        logger.error(f"❌ Ошибка расшифрования: {e}")
        return None
