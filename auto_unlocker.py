"""
Автоматическое открытие замка TTLock каждый день в заданное время.
Скрипт для запуска в Docker-контейнере.
Все параметры берутся из .env (client_id, client_secret, username, password, lock_id, telegram).
Если lock_id не задан — определяется при первом запуске и используется до перезапуска.
Важные события отправляются в Telegram и пишутся в лог с ротацией (14 дней).
"""
import requests
import json
import time as time_module
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
import re
from telegram_utils import send_email_notification
import sys

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

# Email-уведомления
EMAIL_TO = os.getenv("EMAIL_TO")
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

REQUIRED_ENV_VARS = [
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
    'SMTP_PASSWORD',
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

# Глобальная переменная для хранения смещения времени на текущий день
TIME_SHIFT = None

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
# Дублируем логи в stdout для Docker
console = logging.StreamHandler(sys.stdout)
console.setFormatter(formatter)
logger.addHandler(console)

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
        "max_retry_time": "21:00",  # Максимальное время для попыток открытия
        "open_times": {
            "Пн": "09:00",
            "Вт": "09:00",
            "Ср": "09:00",
            "Чт": "09:00",
            "Пт": "09:00",
            "Сб": None,
            "Вс": None
        },
        "breaks": {
            "Пн": [],
            "Вт": [],
            "Ср": [],
            "Чт": [],
            "Пт": [],
            "Сб": [],
            "Вс": []
        }
    }
    try:
        if DEBUG:
            log_message("DEBUG", f"Чтение конфигурации из {CONFIG_PATH}")
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Обновляем только те значения, которые явно указаны в файле
            for key, value in config.items():
                if value is not None:  # Обновляем только если значение не None
                    default[key] = value
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
    При неудаче делает повторные попытки с новой логикой.
    """
    # Получаем LOCK_ID из переменных окружения
    LOCK_ID = os.getenv('TTLOCK_LOCK_ID')

    logger.info("\n[%s] Запуск задачи открытия замка...", ttlock_api.get_now().strftime("%Y-%m-%d %H:%M:%S"))

    # Получаем текущее время в нужном часовом поясе
    now = ttlock_api.get_now()
    current_time = now.strftime("%H:%M")

    # Преобразуем день недели в русский формат
    day_mapping = {
        "monday": "Пн",
        "tuesday": "Вт",
        "wednesday": "Ср",
        "thursday": "Чт",
        "friday": "Пт",
        "saturday": "Сб",
        "sunday": "Вс"
    }
    current_day = day_mapping.get(now.strftime("%A").lower())

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

    # Если есть смещение времени, используем его
    if TIME_SHIFT:
        open_time = TIME_SHIFT
        logger.info(f"Используем смещенное время открытия: {open_time}")

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

        # --- Новая логика повторных попыток ---

        last_error = ""

        def try_unlock(attempt_str: str) -> bool:
            """Вспомогательная функция для одной попытки открытия."""
            nonlocal last_error
            result = ttlock_api.unlock_lock(token, LOCK_ID, logger)
            if result.get("errcode") == 0:
                send_telegram_message(f"✅ <b>Замок успешно открыт (попытка {attempt_str})</b>")
                logger.info(f"Замок успешно открыт (попытка {attempt_str})")
                return True
            else:
                last_error = result.get('errmsg', 'Неизвестная ошибка')
                send_telegram_message(f"⚠️ <b>Попытка {attempt_str}: ошибка</b>\n{last_error}")
                logger.error(f"Попытка {attempt_str}: ошибка - {last_error}")
                return False

        # Первые 3 быстрые попытки
        if try_unlock("1"): return
        time_module.sleep(30)
        if try_unlock("2"): return
        time_module.sleep(60)
        if try_unlock("3"): return

        send_telegram_message("❗️ <b>Не удалось открыть замок после 3 быстрых попыток.</b>")

        # Попытка через 5 минут
        logger.info("Ожидание 5 минут перед следующей попыткой...")
        time_module.sleep(5 * 60)
        if try_unlock("4 (через 5 мин)"): return

        # Попытка через 10 минут
        logger.info("Ожидание 10 минут перед следующей попыткой...")
        time_module.sleep(10 * 60)
        if try_unlock("5 (через 10 мин)"): return

        # Отправка email после 5 неудачных попыток
        logger.error("Не удалось открыть замок после 5 попыток. Отправка email-уведомления.")
        send_telegram_message("❗️ <b>Критическая ошибка: не удалось открыть замок после 5 попыток. Отправляю email.</b>")
        send_email_notification(
            subject=f"Критическая ошибка TTLock: Замок {LOCK_ID} не открывается",
            body=f"Замок с ID {LOCK_ID} не удалось открыть после 5 попыток.\nПоследняя ошибка: {last_error}"
        )

        # Последние 5 попыток (каждые 15 минут)
        for i in range(5):
            attempt_str = f"{i + 6} (каждые 15 мин)"
            logger.info(f"Ожидание 15 минут перед попыткой #{i + 6}...")
            time_module.sleep(15 * 60)
            if try_unlock(attempt_str): return

        # Если все попытки исчерпаны
        final_error_msg = f"❗️❗️❗️ <b>ВСЕ 10 ПОПЫТОК ИСЧЕРПАНЫ. Замок не открыт.</b>\nПоследняя ошибка: {last_error}\nТребуется ручное вмешательство."
        logger.error(final_error_msg)
        send_telegram_message(final_error_msg)

    else:
        logger.info(f"Текущее время {current_time} не совпадает с временем открытия {open_time}")

def log_heartbeat():
    """
    Логирует сообщение о том, что сервис работает.
    """
    next_run = schedule.next_run
    next_run_time = next_run.strftime('%Y-%m-%d %H:%M:%S') if next_run else "Нет запланированных задач"
    logger.info(f"Планировщик активен. Следующая задача в: {next_run_time}")

def main() -> None:
    """
    Основная функция: настраивает и запускает планировщик задач.
    """
    global TIME_SHIFT

    # Сбрасываем смещение времени при старте
    TIME_SHIFT = None

    config = load_config()
    if not config.get("schedule_enabled", True):
        msg = "Расписание отключено в конфигурации."
        print(msg)
        logger.info(msg)
        send_telegram_message(f"ℹ️ <b>{msg}</b>")
        # Не завершаем программу, а просто не планируем задачи
        while True:
            time_module.sleep(60)  # Проверяем каждую минуту
            config = load_config()  # Перечитываем конфигурацию
            if config.get("schedule_enabled", True):
                break  # Если расписание включено, выходим из цикла
        # После выхода из цикла продолжаем настройку задач

    # Настраиваем задачи для каждого дня недели
    for day, time in config.get("open_times", {}).items():
        if not time:
            continue
        # Удаляем пробелы
        time = str(time).strip()
        # Отладочный вывод
        print(f"[DEBUG] day={day}, time={time!r}")
        logger.debug(f"day={day}, time={time!r}")
        # Проверяем формат времени
        if not re.match(r'^[0-2][0-9]:[0-5][0-9]$', time):
            print(f"[ERROR] Некорректный формат времени для дня {day}: {time!r}")
            logger.error(f"Некорректный формат времени для дня {day}: {time!r}")
            continue
        hour, minute = map(int, time.split(':'))
        time = f"{hour:02d}:{minute:02d}"

        # Задача открытия
        schedule.every().monday.at(time).do(job) if day == "Пн" else None
        schedule.every().tuesday.at(time).do(job) if day == "Вт" else None
        schedule.every().wednesday.at(time).do(job) if day == "Ср" else None
        schedule.every().thursday.at(time).do(job) if day == "Чт" else None
        schedule.every().friday.at(time).do(job) if day == "Пт" else None
        schedule.every().saturday.at(time).do(job) if day == "Сб" else None
        schedule.every().sunday.at(time).do(job) if day == "Вс" else None

        # Задачи для перерывов
        breaks = config.get("breaks", {}).get(day, [])
        for break_time in breaks:
            start_time, end_time = break_time.split("-")
            # Удаляем пробелы
            start_time = str(start_time).strip()
            end_time = str(end_time).strip()
            # Отладочный вывод
            print(f"[DEBUG] break for {day}: start={start_time!r}, end={end_time!r}")
            logger.debug(f"break for {day}: start={start_time!r}, end={end_time!r}")
            # Проверяем формат времени
            if not re.match(r'^[0-2][0-9]:[0-5][0-9]$', start_time) or not re.match(r'^[0-2][0-9]:[0-5][0-9]$', end_time):
                print(f"[ERROR] Некорректный формат времени перерыва для дня {day}: {break_time!r}")
                logger.error(f"Некорректный формат времени перерыва для дня {day}: {break_time!r}")
                continue
            start_hour, start_minute = map(int, start_time.split(':'))
            end_hour, end_minute = map(int, end_time.split(':'))
            start_time = f"{start_hour:02d}:{start_minute:02d}"
            end_time = f"{end_hour:02d}:{end_minute:02d}"

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
            schedule.every().monday.at(start_time).do(make_close()) if day == "Пн" else None
            schedule.every().tuesday.at(start_time).do(make_close()) if day == "Вт" else None
            schedule.every().wednesday.at(start_time).do(make_close()) if day == "Ср" else None
            schedule.every().thursday.at(start_time).do(make_close()) if day == "Чт" else None
            schedule.every().friday.at(start_time).do(make_close()) if day == "Пт" else None
            schedule.every().saturday.at(start_time).do(make_close()) if day == "Сб" else None
            schedule.every().sunday.at(start_time).do(make_close()) if day == "Вс" else None

            # Открытие после перерыва
            schedule.every().monday.at(end_time).do(make_reopen()) if day == "Пн" else None
            schedule.every().tuesday.at(end_time).do(make_reopen()) if day == "Вт" else None
            schedule.every().wednesday.at(end_time).do(make_reopen()) if day == "Ср" else None
            schedule.every().thursday.at(end_time).do(make_reopen()) if day == "Чт" else None
            schedule.every().friday.at(end_time).do(make_reopen()) if day == "Пт" else None
            schedule.every().saturday.at(end_time).do(make_reopen()) if day == "Сб" else None
            schedule.every().sunday.at(end_time).do(make_reopen()) if day == "Вс" else None

    # Добавляем задачу-"пульс"
    schedule.every().hour.do(log_heartbeat)

    msg = "Планировщик запущен и ожидает задач."
    print(msg)
    logger.info(msg)
    send_telegram_message(f"ℹ️ <b>{msg}</b>")

    while True:
        schedule.run_pending()
        time_module.sleep(1)

if __name__ == "__main__":
    main()

