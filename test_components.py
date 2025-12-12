#!/usr/bin/env python3
"""
Тестовый скрипт для проверки всех компонентов UI-бота.
Запуск: python3 test_components.py
"""

import sys
import os
from dotenv import load_dotenv

# Цветной вывод для терминала
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}\n")

def print_success(text):
    print(f"{Colors.GREEN}✅ {text}{Colors.RESET}")

def print_error(text):
    print(f"{Colors.RED}❌ {text}{Colors.RESET}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.RESET}")

def test_imports():
    """Тест 1: Проверка импортов."""
    print_header("ТЕСТ 1: Проверка импортов")
    
    tests_passed = 0
    tests_total = 3
    
    try:
        import main
        print_success("main.py импортирован")
        tests_passed += 1
    except Exception as e:
        print_error(f"Ошибка импорта main.py: {e}")
    
    try:
        import user_db_handler
        print_success("user_db_handler.py импортирован")
        tests_passed += 1
    except Exception as e:
        print_error(f"Ошибка импорта user_db_handler.py: {e}")
    
    try:
        import crypto_utils
        print_success("crypto_utils.py импортирован")
        tests_passed += 1
    except Exception as e:
        print_error(f"Ошибка импорта crypto_utils.py: {e}")
    
    return tests_passed == tests_total

def test_env_variables():
    """Тест 2: Проверка переменных окружения."""
    print_header("ТЕСТ 2: Проверка переменных окружения")
    
    load_dotenv('.env')
    
    # Canonical token name used by the project
    canonical_token_key = "BOT_TOKEN"
    deprecated_token_keys = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_BOT_TOKEN_UI")

    required_vars = {
        'ENCRYPTION_KEY': 'Ключ шифрования (Fernet)',
        'PORT': 'Порт API-сервера',
    }

    optional_vars = {
        'SUPABASE_URL': 'URL Supabase проекта (опционально, только для внешних таблиц)',
        'SUPABASE_KEY': 'Публичный ключ Supabase (опционально)',
        'ADMIN_USER_ID': 'Root admin Telegram user id (опционально)',
    }
    
    tests_passed = 0
    tests_total = len(required_vars) + 1  # +1 for telegram token

    # Telegram token: require BOT_TOKEN, warn on deprecated aliases
    canonical_value = (os.getenv(canonical_token_key) or "").strip()
    if canonical_value:
        print_success(f"{canonical_token_key}: Токен Telegram-бота [set, len={len(canonical_value)}]")
        tests_passed += 1
    else:
        # If token is present only under deprecated keys, emit a clear hint.
        deprecated_found = None
        for k in deprecated_token_keys:
            if (os.getenv(k) or "").strip():
                deprecated_found = k
                break
        if deprecated_found:
            print_error(
                f"{canonical_token_key}: НЕ УСТАНОВЛЕН. Токен найден в deprecated переменной {deprecated_found} — "
                f"переименуйте её в {canonical_token_key}."
            )
        else:
            print_error(f"{canonical_token_key}: НЕ УСТАНОВЛЕН (Токен Telegram-бота)")

    for var, desc in required_vars.items():
        value = (os.getenv(var) or "").strip()
        if value:
            # Не печатаем секреты целиком в терминал
            print_success(f"{var}: {desc} [set, len={len(value)}]")
            tests_passed += 1
        else:
            print_error(f"{var}: НЕ УСТАНОВЛЕН ({desc})")

    # Опциональные переменные не должны валить тесты
    for var, desc in optional_vars.items():
        value = (os.getenv(var) or "").strip()
        if value:
            print_success(f"{var}: {desc} [set]")
        else:
            print_warning(f"{var}: НЕ УСТАНОВЛЕН ({desc})")
    
    return tests_passed == tests_total

def test_supabase():
    """Тест 3: Проверка подключения к Supabase."""
    print_header("ТЕСТ 3: Проверка Supabase")
    
    try:
        from supabase import create_client
        
        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')
        
        if not url or not key:
            print_warning("Supabase не настроен (SUPABASE_URL/SUPABASE_KEY отсутствуют) — это допустимо для UI-бота")
            return True
        
        supabase = create_client(url, key)
        print_success(f"Supabase клиент создан для проекта: {url}")
        
        # Попытка простого запроса
        try:
            result = supabase.table("signal_requests").select("id").limit(1).execute()
            print_success("Подключение к таблице signal_requests успешно")
        except Exception as e:
            print_warning(f"Не удалось подключиться к таблице: {e}")
            print_warning("Это нормально, если таблица еще не создана")
        
        return True
        
    except Exception as e:
        print_error(f"Ошибка инициализации Supabase: {e}")
        return False

def test_encryption():
    """Тест 4: Проверка шифрования."""
    print_header("ТЕСТ 4: Проверка шифрования")
    
    try:
        from crypto_utils import encrypt_data, decrypt_data
        
        test_cases = [
            "password123",
            "test@email.com",
            "Тестовый пароль 🔐",
            "a" * 100  # Длинная строка
        ]
        
        tests_passed = 0
        
        for i, test_data in enumerate(test_cases, 1):
            encrypted = encrypt_data(test_data)
            
            if not encrypted:
                print_error(f"Тест {i}: Ошибка шифрования для '{test_data[:20]}...'")
                continue
            
            decrypted = decrypt_data(encrypted)
            
            if decrypted == test_data:
                print_success(f"Тест {i}: '{test_data[:30]}...' -> ✓ Зашифровано/Расшифровано")
                tests_passed += 1
            else:
                print_error(f"Тест {i}: Данные не совпадают после расшифрования")
        
        return tests_passed == len(test_cases)
        
    except Exception as e:
        print_error(f"Ошибка тестирования шифрования: {e}")
        return False

def test_database():
    """Тест 5: Проверка локальной базы данных."""
    print_header("ТЕСТ 5: Проверка базы данных")
    
    try:
        from user_db_handler import init_db, save_encrypted_credentials, get_encrypted_data_from_local_db
        from crypto_utils import encrypt_data
        import asyncio
        
        # Инициализация БД
        init_db()
        print_success("База данных инициализирована")
        
        # Тестовое сохранение
        test_user_id = 999999999
        test_login = encrypt_data("test_login")
        test_password = encrypt_data("test_password")
        
        async def test_db_operations():
            # Сохранение
            await save_encrypted_credentials(test_user_id, test_login, test_password)
            print_success(f"Данные пользователя {test_user_id} сохранены")
            
            # Получение
            credentials = await get_encrypted_data_from_local_db(test_user_id)
            
            if credentials and credentials['login_enc'] == test_login:
                print_success(f"Данные пользователя {test_user_id} получены корректно")
                return True
            else:
                print_error("Полученные данные не совпадают с сохраненными")
                return False
        
        result = asyncio.run(test_db_operations())
        return result
        
    except Exception as e:
        print_error(f"Ошибка тестирования базы данных: {e}")
        return False

def test_api_structure():
    """Тест 6: Проверка структуры API."""
    print_header("ТЕСТ 6: Проверка структуры API")
    
    try:
        from main import api_app
        
        routes = []
        for route in api_app.routes:
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                methods = list(route.methods) if route.methods else ['ANY']
                routes.append(f"{methods[0]} {route.path}")
        
        print_success(f"FastAPI приложение создано с {len(routes)} маршрутами:")
        for route in routes:
            print(f"  • {route}")
        
        expected_routes = ['/', '/health', '/get_po_credentials']
        missing_routes = [r for r in expected_routes if not any(r in route for route in routes)]
        
        if missing_routes:
            print_warning(f"Отсутствуют маршруты: {missing_routes}")
            return False
        
        return True
        
    except Exception as e:
        print_error(f"Ошибка проверки API: {e}")
        return False

def main():
    """Главная функция тестирования."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"🧪 ТЕСТИРОВАНИЕ UI-БОТА")
    print(f"{'='*60}{Colors.RESET}")
    
    # Запуск всех тестов
    tests = [
        ("Импорты модулей", test_imports),
        ("Переменные окружения", test_env_variables),
        ("Подключение Supabase", test_supabase),
        ("Шифрование данных", test_encryption),
        ("Локальная база данных", test_database),
        ("Структура API", test_api_structure)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print_error(f"Критическая ошибка в тесте '{test_name}': {e}")
            results.append((test_name, False))
    
    # Итоговый отчет
    print_header("ИТОГОВЫЙ ОТЧЕТ")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        if result:
            print_success(f"{test_name}")
        else:
            print_error(f"{test_name}")
    
    print(f"\n{Colors.BOLD}Пройдено тестов: {passed}/{total}{Colors.RESET}")
    
    if passed == total:
        print(f"\n{Colors.GREEN}{Colors.BOLD}✨ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!{Colors.RESET}")
        print(f"{Colors.GREEN}🚀 Код готов к деплою на Bothost!{Colors.RESET}\n")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}⚠️  ОБНАРУЖЕНЫ ПРОБЛЕМЫ{Colors.RESET}")
        print(f"{Colors.RED}Исправьте ошибки перед деплоем.{Colors.RESET}\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
