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

def log_message(category: str, message: str):
    """
    Унифицированная функция для логирования сообщений.
    
    Args:
        category: Категория сообщения (ERROR, INFO, DEBUG)
        message: Текст сообщения
    """
    if category == "ERROR":
        print(f"[ERROR] {message}")
        logger.error(message)
    elif category == "INFO":
        print(f"[INFO] {message}")
        logger.info(message)
    elif DEBUG and category == "DEBUG":
        print(f"[DEBUG] {message}")
        logger.debug(message)

def load_config() -> Dict[str, Any]:
    """
    Загружает конфигурацию из файла.
    """
    default = {
        "timezone": "Asia/Krasnoyarsk",  # Используем поддерживаемый часовой пояс
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
            "monday": [],
            "tuesday": [],
            "wednesday": [],
            "thursday": [],
            "friday": [],
            "saturday": [],
            "sunday": []
        }
    }
    try:
        if DEBUG:
            log_message("DEBUG", f"Чтение конфигурации из {CONFIG_PATH}")
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Объединяем с дефолтными значениями
            default.update(config)
            return default
    except Exception as e:
        log_message("ERROR", f"Ошибка чтения конфигурации: {e}")
        return default

def save_config(cfg: Dict[str, Any]) -> None:
    """
    Сохраняет конфигурацию в файл.
    """
    try:
        log_message("DEBUG", f"Сохранение конфигурации в {CONFIG_PATH}")
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_message("ERROR", f"Ошибка сохранения конфигурации: {e}")
        raise

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
    Основная задача: проверяет время и открывает замок если нужно.
    При неудаче делает повторные попытки с временным смещением.
    """
    # Получаем LOCK_ID из переменных окружения
    LOCK_ID = os.getenv('TTLOCK_LOCK_ID')

    logger.info("\n[%s] Запуск задачи открытия замка...", ttlock_api.get_now().strftime("%Y-%m-%d %H:%M:%S"))

    # Получаем текущее время в нужном часовом поясе
    now = ttlock_api.get_now()
    current_time = now.strftime("%H:%M")
    current_day = now.strftime("%A").lower()

    # Проверяем, нужно ли открывать замок
    cfg = load_config()
    if not cfg.get("schedule_enabled", True):
        logger.info("Расписание отключено")
        return

    # Проверяем время открытия
    open_time = cfg.get("open_times", {}).get(current_day)
    if not open_time:
        logger.info("Сегодня замок не открывается")
        return

    # Проверяем, не перерыв ли сейчас
    breaks = cfg.get("breaks", {}).get(current_day, [])
    for break_time in breaks:
        start, end = break_time.split("-")
        if start <= current_time <= end:
            logger.info("Сейчас перерыв")
            return

    # Если текущее время совпадает с временем открытия
    if current_time == open_time:
        # Получаем токен
        token = ttlock_api.get_token(logger)
        if not token:
            logger.error("Не удалось получить токен")
            send_telegram_message("❗️ <b>Ошибка: не удалось получить токен</b>")
            return

        # Если LOCK_ID не задан, пробуем его получить
        if not LOCK_ID:
            logger.error("LOCK_ID не задан")
            send_telegram_message("❗️ <b>Ошибка: LOCK_ID не задан</b>")
            return

        # Пробуем открыть замок с повторными попытками
        max_retries = 3
        retry_count = 0
        success = False

        while retry_count < max_retries and not success:
            retry_count += 1
            result = ttlock_api.unlock_lock(token, LOCK_ID, logger)

            if result.get("errcode") == 0:
                success = True
                logger.info("Замок успешно открыт")
                send_telegram_message("✅ <b>Замок успешно открыт</b>")
                break
            elif result.get("errcode") == -3037:  # Замок занят
                if retry_count < max_retries:
                    wait_time = 30 if retry_count == 1 else 60  # 30 сек после первой попытки, 1 мин после второй
                    logger.warning(f"Попытка {retry_count}: Замок занят, ожидаем {wait_time} секунд...")
                    send_telegram_message(f"⚠️ <b>Попытка {retry_count}: Замок занят</b>\nОжидаем {wait_time} секунд...")
                    time.sleep(wait_time)
                else:
                    logger.error("Не удалось открыть замок после 3 попыток")
                    send_telegram_message("❗️ <b>Не удалось открыть замок после 3 попыток</b>")
                    # Смещаем время задачи на 15 минут позже
                    new_time = (datetime.strptime(open_time, "%H:%M") + timedelta(minutes=15)).strftime("%H:%M")
                    cfg["open_times"][current_day] = new_time
                    save_config(cfg)
                    logger.info(f"Время открытия смещено на {new_time}")
                    send_telegram_message(f"ℹ️ <b>Время открытия смещено на {new_time}</b>")
            else:
                error_msg = result.get('errmsg', 'Неизвестная ошибка')
                logger.error(f"Ошибка открытия замка: {error_msg}")
                send_telegram_message(f"❗️ <b>Ошибка открытия замка:</b>\n{error_msg}")
                break

        if not success:
            logger.error(f"Не удалось открыть замок после {retry_count} попыток")
            send_telegram_message(f"❗️ <b>Не удалось открыть замок после {retry_count} попыток</b>")
    else:
        logger.info(f"Текущее время {current_time} не совпадает с временем открытия {open_time}")

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

