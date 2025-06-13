"""
Автоматическое открытие замка TTLock каждый день в заданное время.
Скрипт для запуска в Docker-контейнере.
Все параметры берутся из .env (client_id, client_secret, username, password, lock_id, telegram).
Если lock_id не задан — определяется при первом запуске и используется до перезапуска.
Важные события отправляются в Telegram и пишутся в лог с ротацией (14 дней).
"""
import requests
import json
import time
import hashlib
import urllib3
import schedule
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging
from logging.handlers import TimedRotatingFileHandler
import ttlock_api
from typing import Optional, Dict, List, Any, Union

# Определяем путь к .env: сначала из ENV_PATH, иначе env/.env
ENV_PATH = os.getenv('ENV_PATH') or 'env/.env'
# Загрузка переменных окружения
load_dotenv(ENV_PATH)

# Уровень отладки
DEBUG = os.getenv('DEBUG', '0').lower() in ('1', 'true', 'yes')

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# TTLock API параметры из .env
client_id = os.getenv("TTLOCK_CLIENT_ID")
client_secret = os.getenv("TTLOCK_CLIENT_SECRET")
username = os.getenv("TTLOCK_USERNAME")
password = os.getenv("TTLOCK_PASSWORD")

# Telegram параметры
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

REQUIRED_ENV_VARS = [
    'TTLOCK_CLIENT_ID',
    'TTLOCK_CLIENT_SECRET',
    'TTLOCK_USERNAME',
    'TTLOCK_PASSWORD',
    'TELEGRAM_BOT_TOKEN',
    'TELEGRAM_CHAT_ID',
]

missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    print(f"[ERROR] Не заданы обязательные переменные окружения: {', '.join(missing_vars)}. Проверьте .env файл!")
    exit(1)

if not all([client_id, client_secret, username, password]):
    raise RuntimeError("Не заданы все переменные окружения TTLOCK_CLIENT_ID, TTLOCK_CLIENT_SECRET, TTLOCK_USERNAME, TTLOCK_PASSWORD. Проверьте .env файл!")

# Максимум попыток и задержка между ними
MAX_RETRIES = 3
RETRY_DELAY = 2
MAX_RETRY_TIME = 21  # Максимальное время для повторных попыток (21:00)
RETRY_TIME_SHIFT = 15  # Смещение времени на 15 минут при неудаче

# Глобальная переменная для lock_id, если он найден при старте
LOCK_ID = None

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")

LOG_FILENAME = "logs/auto_unlocker.log"
os.makedirs("logs", exist_ok=True)
logger = logging.getLogger("auto_unlocker")
logger.setLevel(logging.INFO)
handler = TimedRotatingFileHandler(LOG_FILENAME, when="midnight", backupCount=14, encoding="utf-8")
formatter = ttlock_api.TZFormatter('%(asctime)s %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger.handlers.clear()
logger.addHandler(handler)

def load_config() -> Dict[str, Any]:
    """
    Загружает настройки из config.json. Если нет файла — возвращает дефолтные значения.
    
    Returns:
        dict: Конфигурация с настройками
    """
    default = {
        "timezone": "Asia/Novosibirsk",
        "schedule_enabled": True,
        "open_times": {
            "monday": "09:00",
            "tuesday": "09:00",
            "wednesday": "09:00",
            "thursday": "09:00",
            "friday": "09:00",
            "saturday": None,
            "sunday": None
        },
        "breaks": {
            "monday": ["13:00-14:00"],
            "tuesday": [],
            "wednesday": [],
            "thursday": [],
            "friday": [],
            "saturday": [],
            "sunday": []
        }
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Ошибка загрузки конфигурации: {str(e)}. Используем значения по умолчанию.")
        return default

def send_telegram_message(text: str) -> None:
    """
    Отправляет сообщение в Telegram, если заданы токен и chat_id.
    
    Args:
        text: Текст сообщения
    """
    if not telegram_token or not telegram_chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы, Telegram-уведомление не отправлено.")
        return
        
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {
        "chat_id": telegram_chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"Ошибка отправки Telegram: {resp.text}")
    except Exception as e:
        logger.warning(f"Ошибка отправки Telegram: {str(e)}")

def debug_request(name: str, url: str, data: Dict[str, Any], response: requests.Response) -> None:
    """
    Подробный отладочный вывод HTTP-запроса и ответа.
    
    Args:
        name: Название операции
        url: URL запроса
        data: Данные запроса
        response: Ответ requests
    """
    print(f"\n[DEBUG] {name}")
    print(f"URL: {url}")
    print(f"Параметры запроса: {json.dumps(data, ensure_ascii=False)}")
    print(f"Статус ответа: {response.status_code}")
    try:
        print(f"Тело ответа: {json.dumps(response.json(), ensure_ascii=False)}")
    except Exception:
        print(f"Тело ответа (не JSON): {response.text}")

def resolve_lock_id(token: str) -> Optional[str]:
    """
    Пытается получить lock_id из .env, либо из первого замка в списке.
    
    Args:
        token: access_token
    
    Returns:
        str: lock_id или None в случае ошибки
    """
    lock_id_env = os.getenv("TTLOCK_LOCK_ID")
    if lock_id_env:
        if DEBUG:
            print(f"lock_id найден в .env: {lock_id_env}")
        logger.info(f"lock_id найден в .env: {lock_id_env}")
        send_telegram_message(f"ℹ️ lock_id найден в .env: <code>{lock_id_env}</code>")
        return lock_id_env
        
    locks = ttlock_api.list_locks(token)
    if not locks:
        msg = "Замки не найдены. Проверьте права доступа."
        print(msg)
        logger.error(msg)
        send_telegram_message(f"❗️ <b>Ошибка: замки не найдены</b>")
        return None
        
    first_lock = locks[0]
    lock_id = first_lock.get('lockId')
    msg = f"lock_id выбран из списка: {lock_id}"
    print(msg)
    logger.info(msg)
    send_telegram_message(f"ℹ️ lock_id выбран из списка: <code>{lock_id}</code>")
    return lock_id

def job() -> None:
    """
    Основная задача: открыть замок в заданное время.
    При неудаче делает повторные попытки с временным смещением.
    """
    global LOCK_ID
    now = ttlock_api.get_now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    msg = f"\n[{now_str}] Запуск задачи открытия замка..."
    print(msg)
    logger.info(msg)
    send_telegram_message(f"🔔 <b>Запуск задачи открытия замка</b>\n{now_str}")
    
    token = ttlock_api.get_token(logger)
    if not token:
        msg = "Не удалось получить токен, задача пропущена."
        print(msg)
        logger.error(msg)
        send_telegram_message(f"❗️ <b>Ошибка: не удалось получить токен</b>")
        return

    if LOCK_ID is None:
        LOCK_ID = resolve_lock_id(token)
        if not LOCK_ID:
            msg = "Не удалось определить lock_id, задача пропущена."
            print(msg)
            logger.error(msg)
            send_telegram_message(f"❗️ <b>Ошибка: не удалось определить lock_id</b>")
            return

    result = ttlock_api.unlock_lock(token, LOCK_ID, logger, send_telegram_message)
    if not result.get("success"):
        msg = f"Не удалось открыть замок после {result.get('attempt')} попыток."
        print(msg)
        logger.error(msg)
        send_telegram_message(f"❗️ <b>Ошибка: {msg}</b>")
        return

    msg = f"✅ Замок успешно открыт (попытка {result.get('attempt')})"
    print(msg)
    logger.info(msg)
    send_telegram_message(f"✅ <b>Замок успешно открыт</b>\nПопытка: {result.get('attempt')}")

def main() -> None:
    """
    Основная функция: настраивает и запускает планировщик задач.
    """
    config = load_config()
    if not config.get("schedule_enabled", True):
        msg = "Расписание отключено в конфигурации."
        print(msg)
        logger.info(msg)
        send_telegram_message(f"ℹ️ <b>{msg}</b>")
        return

    # Настраиваем задачи для каждого дня недели
    for day, time in config.get("open_times", {}).items():
        if not time:
            continue
            
        # Задача открытия
        schedule.every().monday.at(time).do(job) if day == "monday" else None
        schedule.every().tuesday.at(time).do(job) if day == "tuesday" else None
        schedule.every().wednesday.at(time).do(job) if day == "wednesday" else None
        schedule.every().thursday.at(time).do(job) if day == "thursday" else None
        schedule.every().friday.at(time).do(job) if day == "friday" else None
        schedule.every().saturday.at(time).do(job) if day == "saturday" else None
        schedule.every().sunday.at(time).do(job) if day == "sunday" else None

        # Задачи для перерывов
        breaks = config.get("breaks", {}).get(day, [])
        for break_time in breaks:
            start_time, end_time = break_time.split("-")
            
            def make_close(day=day):
                def _close():
                    token = ttlock_api.get_token(logger)
                    if token and LOCK_ID:
                        ttlock_api.lock_lock(token, LOCK_ID, logger, send_telegram_message)
                return _close

            def make_reopen(day=day):
                def _open():
                    token = ttlock_api.get_token(logger)
                    if token and LOCK_ID:
                        ttlock_api.unlock_lock(token, LOCK_ID, logger, send_telegram_message)
                return _open

            # Закрытие в начале перерыва
            schedule.every().monday.at(start_time).do(make_close()) if day == "monday" else None
            schedule.every().tuesday.at(start_time).do(make_close()) if day == "tuesday" else None
            schedule.every().wednesday.at(start_time).do(make_close()) if day == "wednesday" else None
            schedule.every().thursday.at(start_time).do(make_close()) if day == "thursday" else None
            schedule.every().friday.at(start_time).do(make_close()) if day == "friday" else None
            schedule.every().saturday.at(start_time).do(make_close()) if day == "saturday" else None
            schedule.every().sunday.at(start_time).do(make_close()) if day == "sunday" else None

            # Открытие после перерыва
            schedule.every().monday.at(end_time).do(make_reopen()) if day == "monday" else None
            schedule.every().tuesday.at(end_time).do(make_reopen()) if day == "tuesday" else None
            schedule.every().wednesday.at(end_time).do(make_reopen()) if day == "wednesday" else None
            schedule.every().thursday.at(end_time).do(make_reopen()) if day == "thursday" else None
            schedule.every().friday.at(end_time).do(make_reopen()) if day == "friday" else None
            schedule.every().saturday.at(end_time).do(make_reopen()) if day == "saturday" else None
            schedule.every().sunday.at(end_time).do(make_reopen()) if day == "sunday" else None

    msg = "Планировщик запущен и ожидает задач."
    print(msg)
    logger.info(msg)
    send_telegram_message(f"ℹ️ <b>{msg}</b>")

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()

