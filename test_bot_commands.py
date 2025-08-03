#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы команд Telegram-бота.
Запускается локально для диагностики проблем.
"""
import os
import sys
import json
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv('env/.env')

def test_env_variables():
    """Проверяет наличие всех необходимых переменных окружения."""
    print("🔍 Проверка переменных окружения...")
    
    required_vars = [
        'TTLOCK_CLIENT_ID',
        'TTLOCK_CLIENT_SECRET', 
        'TTLOCK_USERNAME',
        'TTLOCK_PASSWORD',
        'TELEGRAM_BOT_TOKEN',
        'TELEGRAM_CHAT_ID',
        'EMAIL_TO',
        'SMTP_SERVER',
        'SMTP_PORT',
        'SMTP_USER',
        'SMTP_PASSWORD'
    ]
    
    missing_vars = []
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            missing_vars.append(var)
            print(f"❌ {var}: не задан")
        else:
            print(f"✅ {var}: {'*' * len(value)}")
    
    if missing_vars:
        print(f"\n❌ Отсутствуют переменные: {', '.join(missing_vars)}")
        return False
    else:
        print("\n✅ Все переменные окружения заданы")
        return True

def test_config_file():
    """Проверяет файл конфигурации."""
    print("\n🔍 Проверка файла config.json...")
    
    if not os.path.exists('config.json'):
        print("❌ Файл config.json не найден")
        return False
    
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        required_keys = ['timezone', 'schedule_enabled', 'open_times', 'breaks']
        missing_keys = []
        
        for key in required_keys:
            if key not in config:
                missing_keys.append(key)
                print(f"❌ {key}: отсутствует")
            else:
                print(f"✅ {key}: присутствует")
        
        if missing_keys:
            print(f"\n❌ Отсутствуют ключи: {', '.join(missing_keys)}")
            return False
        else:
            print("\n✅ Конфигурация корректна")
            return True
            
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга JSON: {e}")
        return False
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        return False

def test_file_permissions():
    """Проверяет права доступа к файлам."""
    print("\n🔍 Проверка прав доступа...")
    
    files_to_check = [
        ('config.json', 'r'),
        ('env/.env', 'r'),
        ('logs/', 'r')
    ]
    
    all_ok = True
    for file_path, mode in files_to_check:
        if os.path.exists(file_path):
            if os.access(file_path, os.R_OK if 'r' in mode else 0):
                print(f"✅ {file_path}: доступен для чтения")
            else:
                print(f"❌ {file_path}: нет прав на чтение")
                all_ok = False
        else:
            print(f"⚠️ {file_path}: файл не найден")
    
    return all_ok

def test_imports():
    """Проверяет импорт модулей."""
    print("\n🔍 Проверка импорта модулей...")
    
    modules = [
        'telegram_bot',
        'telegram_utils', 
        'ttlock_api',
        'auto_unlocker'
    ]
    
    all_ok = True
    for module in modules:
        try:
            __import__(module)
            print(f"✅ {module}: импортирован успешно")
        except ImportError as e:
            print(f"❌ {module}: ошибка импорта - {e}")
            all_ok = False
    
    return all_ok

def main():
    """Основная функция тестирования."""
    print("🚀 Запуск диагностики TTLockUnlocker...\n")
    
    tests = [
        ("Переменные окружения", test_env_variables),
        ("Файл конфигурации", test_config_file),
        ("Права доступа", test_file_permissions),
        ("Импорт модулей", test_imports)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Ошибка в тесте {test_name}: {e}")
            results.append((test_name, False))
    
    print("\n" + "="*50)
    print("📊 РЕЗУЛЬТАТЫ ДИАГНОСТИКИ:")
    print("="*50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ ПРОЙДЕН" if result else "❌ ПРОВАЛЕН"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\nИтого: {passed}/{len(results)} тестов пройдено")
    
    if passed == len(results):
        print("\n🎉 Все тесты пройдены! Система готова к работе.")
        print("\nДля запуска выполните:")
        print("  docker-compose up -d")
    else:
        print("\n⚠️ Обнаружены проблемы. Исправьте их перед запуском.")
        print("\nРекомендации:")
        print("1. Проверьте файл env/.env")
        print("2. Убедитесь, что config.json существует и корректен")
        print("3. Проверьте права доступа к файлам")
        print("4. Установите недостающие зависимости")

if __name__ == "__main__":
    main() 